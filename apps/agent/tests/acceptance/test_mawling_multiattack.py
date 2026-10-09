"""The authored Mawling sequence reaches the DM through public commands."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance.mawling_harness import MawlingHarness

import db_mutations
import db_queries
from creature_combat import translate_creature
from creature_schema import validate_creature_stat_block


@pytest.fixture
def mock_combat_agent_factory():
    return None


@pytest.fixture
async def maw(reset_db_pool, request):
    harness = MawlingHarness()
    try:
        await harness.start(reactions=getattr(request, "param", False))
        yield harness
    finally:
        if hasattr(harness, "session"):
            await harness.close()


async def test_catalog_composite_is_public_and_survives_reload(maw):
    actor = next(p for p in maw.roster if p["id"] == maw.enemies[0])
    assert actor["actions"] == ["Claw", "Dissolution Maw", "Lunge", "Multiattack"]
    composite = maw.composite(maw.players)
    assert [s["action"] for s in composite["strikes"]] == ["Claw", "Dissolution Maw"]
    await maw.reload()
    result = await maw.declare(maw.players)
    reloaded = next(p for p in result["participants"] if p["id"] == actor["id"])
    assert reloaded["executable_actions"] == actor["executable_actions"]


def catalog():
    return json.loads((Path(__file__).resolve().parents[4] / "content/creatures.json").read_text())


@pytest.mark.parametrize(
    "sequence",
    [
        None,
        {},
        {"name": "", "attacks": ["Claw"]},
        {"name": "Claw", "attacks": ["Claw"]},
        {"name": "Multiattack", "attacks": []},
        {"name": "Multiattack", "attacks": ["unknown"]},
        {"name": "Multiattack", "attacks": [3]},
    ],
)
def test_python_rejects_invalid_catalog_sequence(sequence):
    row = copy.deepcopy(next(r for r in catalog() if r["id"] == "hollow_mawling"))
    row["multiattack_sequence"] = sequence
    assert validate_creature_stat_block(row)


@pytest.mark.parametrize("change", ["active_only", "ambiguous", "malformed", "name_collision"])
def test_python_rejects_unresolvable_sequence(change):
    row = copy.deepcopy(next(r for r in catalog() if r["id"] == "hollow_mawling"))
    if change == "active_only":
        row["multiattack_sequence"]["attacks"] = [row["actives"][1]["name"]]
    elif change == "ambiguous":
        row["attacks"].append({**row["attacks"][0], "name": "cLAW"})
    elif change == "malformed":
        row["multiattack_sequence"]["attacks"] = "Claw"
    else:
        row["multiattack_sequence"]["name"] = row["actives"][1]["name"]
    assert validate_creature_stat_block(row)


def test_catalog_roles_and_other_multiattacks():
    rows = catalog()
    mawling = next(r for r in rows if r["id"] == "hollow_mawling")
    assert mawling["multiattack_sequence"] == {"name": "Multiattack", "attacks": ["Claw", "Dissolution Maw"]}
    assert validate_creature_stat_block(mawling) == []
    repeated = copy.deepcopy(mawling)
    repeated["multiattack_sequence"]["attacks"] = ["claw", "CLAW"]
    assert validate_creature_stat_block(repeated) == []
    for row in rows:
        if row["multiattack"] is None:
            continue
        for role in ("standard", "elite", "boss", "minion"):
            enemy = translate_creature(row, encounter_id="test", enemy_id="test", role=role)
            executes = row["id"] == "hollow_mawling" and role != "minion"
            assert bool(enemy.get("multiattack_sequence")) is executes
            assert any(e["group"] == "multiattack" for e in enemy["deferred_effects"]) is not executes


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
    for _ in range(8):
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


@pytest.mark.parametrize("same,miss", [(False, False), (True, False), (False, True)])
async def test_public_selection_resolves_authored_math(maw, dice, same, miss):
    expressions, d20 = dice
    if miss:
        d20.return_value = SimpleNamespace(total=1)
    targets = [maw.players[0], maw.players[0] if same else maw.players[1]]
    await maw.declare(targets)
    assert len(maw.sd.combat_state.pending_declarations) == 4
    assert maw.sd.combat_state.pending_declarations[maw.enemies[0]]["type"] == "multiattack"
    packets, _ = await drain(maw)
    strikes = blows(packets)
    assert [s["action"] for s in strikes] == ["Claw", "Dissolution Maw"]
    assert [s["target_id"] for s in strikes] == targets
    assert [s["strike_index"] for s in strikes] == [0, 1]
    assert len({s["held_seq"] for s in strikes}) == len({s["execution_id"] for s in strikes}) == 2
    assert [s["hit"] for s in strikes] == [not miss, not miss]
    assert [s["damage"] for s in strikes] == ([0, 0] if miss else [8, 12])
    assert [s["damage_type"] for s in strikes] == ["slashing", "necrotic"]
    assert expressions == ([] if miss else ["1d8+2", "2d6+2"])
    assert [s["attack_total"] for s in strikes] == ([6, 6] if miss else [20, 20])
    await assert_hp(maw, [100, 100] if miss else [80, 100] if same else [92, 88])


@pytest.mark.parametrize(
    "defect",
    [
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
    ],
)
async def test_public_invalid_composite_is_atomic(maw, defect):
    payload = maw.composite(maw.players)
    strikes = payload["strikes"]
    if defect == "missing_target":
        strikes[1].pop("target_id")
    elif defect in ("zero", "one", "three"):
        payload["strikes"] = (strikes * 2)[: {"zero": 0, "one": 1, "three": 3}[defect]]
    elif defect == "unknown_action":
        strikes[1]["action"] = "unknown"
    elif defect == "reverse":
        strikes.reverse()
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


@pytest.mark.parametrize("maw", [True], indirect=True)
async def test_every_strike_pause_reloads_without_reroll(maw, dice):
    await maw.declare([maw.players[0]] * 2)
    ids = {}

    async def checkpoint(state, window):
        head = state.held_actions[0]
        assert window["target_id"] == maw.players[0]
        assert window["action"] == ["Claw", "Dissolution Maw"][head["strike_index"]]
        assert state.get_participant(maw.players[0]).hp_current == (100 if head["strike_index"] == 0 else 92)
        for held in state.held_actions:
            if "strike_index" in held:
                identity = held["seq"], held["execution_id"]
                assert ids.setdefault(held["strike_index"], identity) == identity
        dice[1].side_effect = AssertionError("held strike rerolled") if window["stage"] == "post_roll" else None

    packets, windows = await drain(maw, checkpoints=checkpoint)
    assert [(w["action"], w["stage"]) for w in windows] == [
        (a, stage) for a in ("Claw", "Dissolution Maw") for stage in ("pre_roll", "post_roll")
    ]
    assert len(ids) == 2 and ids[0] != ids[1]
    assert len(blows(packets)) == 2
    await assert_hp(maw, [80, 100])


@pytest.mark.parametrize("maw", ["isolation"], indirect=True)
async def test_first_strike_reaction_spend_cannot_leak_to_second(maw, dice):
    await maw.declare([maw.players[0]] * 2)
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
    packets, windows = await drain(maw)
    assert [s["damage"] for s in blows(packets)] == [4, 12]
    assert [(w["action"], w["stage"]) for w in windows] == [("Dissolution Maw", "post_roll")]
    await assert_hp(maw, [84, 100])


@pytest.mark.parametrize("same", [False, True])
async def test_fallen_first_target_does_not_cancel_other_target(maw, dice, same):
    state = maw.sd.combat_state
    state.get_participant(maw.players[0]).hp_current = 5
    await maw.pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{hp,current}','5') WHERE player_id=$1", maw.players[0]
    )
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    await maw.reload()
    await maw.declare([maw.players[0], maw.players[0] if same else maw.players[1]])
    packets, _ = await drain(maw)
    strikes = blows(packets)
    assert len(strikes) == 2 and strikes[0]["damage"] == 8
    if same:
        assert strikes[1]["resolved"] is False and "fell" in strikes[1]["reason"]
        assert strikes[1]["target_id"] == maw.players[0]
        assert dice[0] == ["1d8+2"]
    else:
        assert strikes[1]["damage"] == 12
    await assert_hp(maw, [0, 100 if same else 88])


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
