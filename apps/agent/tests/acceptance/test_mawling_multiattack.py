"""The authored Mawling sequence reaches the DM through public commands."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance.mawling_harness import MawlingHarness

import db_mutations
import db_queries
from creature_combat import translate_creature


@pytest.fixture
def mock_combat_agent_factory():
    return None


@pytest.fixture
async def maw(reset_db_pool, request):
    harness = MawlingHarness()
    try:
        param = getattr(request, "param", False)
        await harness.start(**param if isinstance(param, dict) else {"reactions": param})
        yield harness
    finally:
        if hasattr(harness, "encounter_id"):
            await harness.close()


@pytest.mark.parametrize(
    "maw,names",
    [
        ({"role": "standard"}, ["Claw", "Dissolution Maw"]),
        ({"role": "elite"}, ["Claw", "Dissolution Maw", "Claw"]),
        ({"role": "boss"}, ["Claw", "Dissolution Maw", "Claw"]),
        ({"role": "minion"}, []),
    ],
    indirect=["maw"],
)
async def test_catalog_composite_is_public_and_survives_reload(maw, names):
    actor = next(p for p in maw.roster if p["id"] == maw.enemies[0])
    composites = [a for a in actor["executable_actions"] if a["kind"] == "multiattack"]
    assert [s["action"] for a in composites for s in a["strikes"]] == names
    assert ("Multiattack" in actor["actions"]) is bool(names)
    await maw.reload()
    if names:
        assert not any(
            e["group"] == "multiattack" for e in maw.sd.combat_state.get_participant(actor["id"]).deferred_effects
        )
        result = await maw.declare([maw.players[0]] * len(names))
    else:
        result = await maw.command(
            "declare_phase", {"declarations": [{"kind": "defend", "actor_id": p} for p in [*maw.players, *maw.enemies]]}
        )
    reloaded = next(p for p in result["participants"] if p["id"] == actor["id"])
    assert reloaded["executable_actions"] == actor["executable_actions"]


def catalog():
    return json.loads((Path(__file__).resolve().parents[4] / "content/creatures.json").read_text())


def test_other_multiattacks_remain_deferred():
    for row in catalog():
        if row["id"] == "hollow_mawling":
            continue
        assert "multiattack_sequence" not in row
        if row["multiattack"] is None:
            continue
        for role in ("standard", "elite", "boss", "minion"):
            enemy = translate_creature(row, encounter_id="test", enemy_id="test", role=role)
            assert not enemy.get("multiattack_sequence")
            assert any(e["group"] == "multiattack" for e in enemy["deferred_effects"])


@pytest.fixture
def dice():
    expressions = []

    def damage(expression, **kwargs):
        expressions.append(expression)
        return SimpleNamespace(total={"1d8+2": 8, "2d6+2": 12}[expression])

    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=15)) as d20,
        patch("check_resolution_attack.dice_roll", side_effect=damage),
    ):
        yield expressions, d20


async def drain(maw, *, checkpoints=None):
    packets = []
    windows = []
    for _ in range(
        2
        + 2
        * len(
            next(
                a
                for p in maw.roster
                if p["id"] == maw.enemies[0]
                for a in p["executable_actions"]
                if a["kind"] == "multiattack"
            )["strikes"]
        )
    ):
        result = await maw.command("resolve_phase", {})
        packets.extend(result["packets"])
        state = await maw.reload()
        if state.beat == "declaration":
            assert state.round_number == 2 and state.held_actions == []
            return packets, windows
        window = result["next"]["waiting_on"]
        if window is None:
            assert state.beat == "narration" and state.held_actions
            continue
        windows.append(window)
        if checkpoints:
            await checkpoints(state, window)
    pytest.fail("held strikes did not drain")


def blows(packets):
    return [p for p in packets if p.get("composite") == "Multiattack"]


async def assert_hp(maw, expected):
    state = await maw.reload()
    for pid, hp in zip(maw.players, expected, strict=True):
        assert state.get_participant(pid).hp_current == hp
        row = await db_queries.get_player(pid)
        assert row is not None and row["hp"]["current"] == hp


@pytest.mark.parametrize("maw", [{"role": "standard"}, {"role": "elite"}], indirect=True)
@pytest.mark.parametrize("same,miss", [(False, False), (True, False), (False, True)])
async def test_public_selection_resolves_authored_math(maw, dice, same, miss):
    expressions, d20 = dice
    if miss:
        d20.return_value = SimpleNamespace(total=1)
    targets = [maw.players[0], maw.players[0] if same else maw.players[1]]
    elite = maw.sd.combat_state.get_participant(maw.enemies[0]).role == "elite"
    if elite:
        targets.append(maw.players[0])
    count = len(targets)
    await maw.declare(targets)
    assert len(maw.sd.combat_state.pending_declarations) == 4
    assert maw.sd.combat_state.pending_declarations[maw.enemies[0]]["type"] == "multiattack"
    packets, _ = await drain(maw)
    strikes = blows(packets)
    assert [s["action"] for s in strikes] == (
        ["Claw", "Dissolution Maw", "Claw"] if elite else ["Claw", "Dissolution Maw"]
    )
    assert [s["target_id"] for s in strikes] == targets
    assert [s["strike_index"] for s in strikes] == list(range(count))
    assert len({s["held_seq"] for s in strikes}) == len({s["execution_id"] for s in strikes}) == count
    assert [s["hit"] for s in strikes] == [not miss] * count
    assert [s["damage"] for s in strikes] == ([0] * count if miss else [10, 15, 10] if elite else [8, 12])
    assert [s["damage_type"] for s in strikes] == (
        ["slashing", "necrotic", "slashing"] if elite else ["slashing", "necrotic"]
    )
    assert expressions == ([] if miss else ["1d8+2", "2d6+2", "1d8+2"] if elite else ["1d8+2", "2d6+2"])
    assert [s["attack_total"] for s in strikes] == ([7 if miss else 21] * 3 if elite else [6 if miss else 20] * 2)
    await assert_hp(
        maw, [100, 100] if miss else ([65, 100] if same else [80, 85]) if elite else [80, 100] if same else [92, 88]
    )


@pytest.mark.parametrize(
    "maw,defect",
    [
        *[
            ({"role": "standard"}, defect)
            for defect in (
                "missing_target",
                "zero",
                "one",
                "three",
                "unknown_action",
                "reverse",
                "unknown_target",
                "friendly",
                "self",
                "no_sequence",
                "injected_math",
            )
        ],
        ({"role": "elite"}, "one"),
        ({"role": "elite"}, "three"),
    ],
    indirect=["maw"],
)
async def test_public_invalid_composite_is_atomic(maw, defect):
    count = 3 if maw.sd.combat_state.get_participant(maw.enemies[0]).role == "elite" else 2
    payload = maw.composite([maw.players[i % 2] for i in range(count)])
    strikes = payload["strikes"]
    if defect == "missing_target":
        strikes[1].pop("target_id")
    elif defect in ("zero", "one", "three"):
        payload["strikes"] = (strikes * 2)[: {"zero": 0, "one": count - 1, "three": count + 1}[defect]]
    elif defect == "unknown_action":
        strikes[1]["action"] = "unknown"
    elif defect == "reverse":
        strikes[0], strikes[1] = strikes[1], strikes[0]
    elif defect in ("unknown_target", "friendly", "self"):
        strikes[1]["target_id"] = {"unknown_target": "unknown", "friendly": maw.enemies[1], "self": maw.enemies[0]}[
            defect
        ]
    elif defect == "no_sequence":
        payload["actor_id"] = maw.players[0]
    else:
        strikes[1]["damage"] = "999d20"
    before = await maw.snapshot()
    await maw.command("declare_phase", {"declarations": [payload]}, error=True)
    assert await maw.snapshot() == before


@pytest.mark.parametrize("maw", [{"reactions": True}, {"reactions": True, "role": "elite"}], indirect=True)
async def test_every_strike_pause_reloads_without_reroll(maw, dice):
    names = [
        s["action"]
        for a in next(p for p in maw.roster if p["id"] == maw.enemies[0])["executable_actions"]
        if a["kind"] == "multiattack"
        for s in a["strikes"]
    ]
    elite = maw.sd.combat_state.get_participant(maw.enemies[0]).role == "elite"
    assert len(names) == (3 if elite else 2)
    await maw.declare([maw.players[0]] * len(names))
    ids = {}

    async def checkpoint(state, window):
        head = state.held_actions[0]
        assert window["target_id"] == maw.players[0]
        assert window["action"] == names[head["strike_index"]]
        assert (
            state.get_participant(maw.players[0]).hp_current
            == ([100, 90, 75] if elite else [100, 92])[head["strike_index"]]
        )
        for held in state.held_actions:
            if "strike_index" in held:
                identity = held["seq"], held["execution_id"]
                assert ids.setdefault(held["strike_index"], identity) == identity
        dice[1].side_effect = AssertionError("held strike rerolled") if window["stage"] == "post_roll" else None

    packets, windows = await drain(maw, checkpoints=checkpoint)
    assert [(w["action"], w["stage"]) for w in windows] == [
        (a, stage) for a in names for stage in ("pre_roll", "post_roll")
    ]
    assert len(ids) == len(names) and len(set(ids.values())) == len(names)
    assert [s["strike_index"] for s in blows(packets)] == list(range(len(names)))
    assert dice[0] == (["1d8+2", "2d6+2", "1d8+2"] if elite else ["1d8+2", "2d6+2"])
    await assert_hp(maw, [65 if elite else 80, 100])


@pytest.mark.parametrize("maw", [{"reactions": "isolation", "role": "elite"}], indirect=True)
async def test_first_strike_reaction_spend_cannot_leak_to_second(maw, dice):
    await maw.declare([maw.players[0]] * 3)
    await maw.command("resolve_phase", {})
    paused = await maw.command("resolve_phase", {})
    window = paused["next"]["waiting_on"]
    assert window["action"] == "Claw" and window["stage"] == "post_roll"
    offered = [r["id"] for r in window["reactions"]]
    assert "rogue_uncanny_dodge" in offered
    await maw.command("activate", {"id": "rogue_uncanny_dodge"})
    state = await maw.reload()
    spend = state.reactions_available[maw.players[0]]
    assert spend["held_seq"] == state.held_actions[0]["seq"]
    assert spend["stage"] == "post_roll"
    before = await maw.snapshot()
    await maw.command("activate", {"id": "rogue_uncanny_dodge"}, error=True)
    assert await maw.snapshot() == before
    identities = {h["strike_index"]: (h["seq"], h["execution_id"]) for h in state.held_actions if "strike_index" in h}
    assert len(set(identities.values())) == 3
    first = await maw.command("resolve_phase", {})
    state = await maw.reload()
    assert first["next"]["waiting_on"]["action"] == "Dissolution Maw"
    assert first["next"]["waiting_on"]["stage"] == "post_roll"
    assert state.get_participant(maw.players[0]).hp_current == 95
    assert {h["strike_index"]: (h["seq"], h["execution_id"]) for h in state.held_actions if "strike_index" in h} == {
        i: identities[i] for i in (1, 2)
    }
    assert state.reactions_available[maw.players[0]] == spend
    packets, windows = await drain(maw)
    packets = first["packets"] + packets
    windows = [first["next"]["waiting_on"], *windows]
    assert [s["damage"] for s in blows(packets)] == [5, 15, 10]
    assert [(w["action"], w["stage"]) for w in windows] == [("Dissolution Maw", "post_roll"), ("Claw", "post_roll")]
    assert [s["strike_index"] for s in blows(packets)] == [0, 1, 2]
    assert dice[0] == ["1d8+2", "2d6+2", "1d8+2"]
    await assert_hp(maw, [70, 100])


@pytest.mark.parametrize("maw", [{"role": "standard"}, {"role": "elite"}, {"role": "boss"}], indirect=True)
@pytest.mark.parametrize("same", [False, True])
async def test_fallen_first_target_does_not_cancel_other_target(maw, dice, same):
    state = maw.sd.combat_state
    state.get_participant(maw.players[0]).hp_current = 5
    state.spatial["positions"][maw.enemies[0]] = {"x": 5, "y": 0, "z": 0}
    claw, maw_damage = {"standard": (8, 12), "elite": (10, 15), "boss": (12, 18)}[
        state.get_participant(maw.enemies[0]).role
    ]
    await maw.pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{hp,current}','5') WHERE player_id=$1", maw.players[0]
    )
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    await maw.reload()
    elite = state.get_participant(maw.enemies[0]).role in ("elite", "boss")
    targets = [maw.players[0], maw.players[0] if same else maw.players[1]]
    if elite:
        targets.append(maw.players[0])
    await maw.declare(targets)
    packets, _ = await drain(maw)
    strikes = blows(packets)
    assert len(strikes) == len(targets) and strikes[0]["damage"] == claw
    if same:
        assert strikes[1]["resolved"] and strikes[1]["hit"]
        assert strikes[1]["damage"] == maw_damage
        assert (await maw.reload()).get_participant(maw.players[0]).death_save_failures == (3 if elite else 2)
        assert strikes[1]["target_id"] == maw.players[0]
        assert dice[0] == (["1d8+2", "2d6+2", "1d8+2"] if elite else ["1d8+2", "2d6+2"])
    else:
        assert strikes[1]["damage"] == maw_damage
    if elite:
        assert strikes[2]["hit"] and strikes[2]["damage"] == claw
    await assert_hp(maw, [0, 100 if same else 100 - maw_damage])


@pytest.mark.parametrize("unavailable", ["first_target", "second_target", "actor_fallen", "actor_disabled"])
async def test_unavailable_strikes_drain_independently_after_reload(maw, dice, unavailable):
    await maw.declare(maw.players)
    await maw.command("resolve_phase", {})
    paused = await maw.command("resolve_phase", {})
    assert paused["next"]["waiting_on"]["action"] == "Claw"
    packets = []
    if unavailable != "first_target":
        # Decline Claw's pre-roll; commit its damage and pause before Maw.
        result = await maw.command("resolve_phase", {})
        packets.extend(result["packets"])
        assert result["next"]["waiting_on"]["action"] == "Dissolution Maw"
    state = await maw.reload()
    if unavailable.startswith("actor"):
        actor = state.get_participant(maw.enemies[0])
        if unavailable == "actor_fallen":
            actor.is_fallen = True
            actor.hp_current = 0
        else:
            actor.conditions = [{"type": "stunned", "duration": 2}]
    else:
        pid = maw.players[0 if unavailable == "first_target" else 1]
        actor = state.get_participant(pid)
        actor.hp_current = 0
        actor.is_fallen = True
        actor.death_save_failures = 3
        await maw.pool.execute("UPDATE players SET data=jsonb_set(data,'{hp,current}','0') WHERE player_id=$1", pid)
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    await maw.reload()
    more, _ = await drain(maw)
    strikes = blows(packets + more)
    assert len(strikes) == 2
    wasted = strikes[0 if unavailable == "first_target" else 1]
    assert wasted["resolved"] is False and wasted["reason"]
    assert wasted["target_id"] == maw.players[0 if unavailable == "first_target" else 1]
    assert dice[0] == (["2d6+2"] if unavailable == "first_target" else ["1d8+2"])
    await assert_hp(
        maw, [0, 88] if unavailable == "first_target" else [92, 0 if unavailable == "second_target" else 100]
    )


@pytest.mark.parametrize("maw", [True], indirect=True)
async def test_reaction_checkpoint_failure_rolls_back_cost_and_spend(maw, dice):
    await maw.declare([maw.players[0]] * 2)
    for _ in range(3):
        await maw.command("resolve_phase", {})
    before = await maw.snapshot()
    with patch("db_mutations.save_combat_state", side_effect=RuntimeError("checkpoint unavailable")):
        await maw.command("activate", {"id": "rogue_uncanny_dodge"}, error=True)
    assert await maw.snapshot() == before
