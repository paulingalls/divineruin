import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _d20
from acceptance.mawling_harness import MawlingHarness
from livekit.agents import AgentSession

import combat_spatial
import db_queries
import reaction_spend
from combat_agent import CombatAgent
from combat_state import CombatState
from conditions import apply_condition
from db_mutations_resonance import read_player_resonance
from session_data import SessionData

Fight = tuple[MawlingHarness, str, str, str]


@pytest.fixture
def mock_combat_agent_factory() -> None:
    return None


@pytest.fixture
async def fight(reset_db_pool, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    monkeypatch.setenv("CONTENT_CACHE_PREFIX", f"slippery_{uuid4().hex}:")
    player_class, action = getattr(request, "param", ("rogue", "Entomb"))
    entomb = action == "Entomb"
    location = "ashmark_architect_works" if entomb else "greyvale_wilderness_north"
    harness = MawlingHarness()
    try:
        await harness.prepare((5,), companion=None, location=location)
        victim = harness.players[0]
        await harness.pool.execute(
            "UPDATE players SET data = jsonb_set(data, '{class}', $2::jsonb) WHERE player_id = $1",
            victim,
            json.dumps(player_class),
        )
        encounter = "ashmark_patrol"
        if entomb:
            scene = await harness.command("enter_location", {"location_id": location})
            encounter = scene["architect"]["encounter_id"]
        entry = await harness.command("enter_mode", {"mode": "combat", "encounter_id": encounter})
        actor = next(
            p["id"]
            for p in entry["participants"]
            if any(a["id"] == action and a["available"] for a in p["executable_actions"])
        )
        state = await harness.reload()
        assert state.spatial is not None
        origin = combat_spatial.position(state.spatial, actor)
        combat_spatial.place(state, victim, {**origin, "x": origin["x"] + 5})
        await harness.persist()
        yield harness, actor, victim, action
    finally:
        await harness.close()


def strike(actor: str, victim: str, action: str) -> dict:
    return {
        "reshape": [],
        "quick_fingers_mode": "",
        "quick_fingers_item": "",
        "kind": "attack",
        "actor_id": actor,
        "target_id": victim,
        "action": action,
        "held_item_id": "",
        "rider": "",
    }


async def declare(harness: MawlingHarness, actor: str, victim: str, action: str) -> None:
    state = await harness.reload()
    await harness.command(
        "declare_phase",
        {
            "declarations": [
                strike(actor, victim, action),
                *({"reshape": [], "kind": "defend", "actor_id": p} for p in state.initiative_order if p != actor),
            ]
        },
    )


async def fresh_session(harness: MawlingHarness) -> None:
    state = await harness.reload()
    await harness.session.aclose()
    if harness.sd.background is not None:
        await harness.sd.background.stop()
    player = harness.players[0]
    harness.sd = SessionData(
        player_id=player, location_id=harness.sd.location_id, room=harness.sd.room, combat_state=state
    )
    resonance = await read_player_resonance(player)
    member = harness.sd.member_state(player)
    member.resonance.current = resonance["current"]
    member.resonance.flickering_bonus = resonance["flickering_bonus"]
    harness.session = AgentSession(llm=harness.model, max_tool_steps=5, userdata=harness.sd)
    await harness.session.start(CombatAgent())


async def advance(harness: MawlingHarness, *, expect_condition_window: bool) -> tuple[list[dict], dict | None]:
    state = harness.sd.combat_state
    assert state is not None
    round_number = state.round_number
    packets = []
    for _ in range(12):
        result = await harness.command("resolve_phase", {})
        packets.extend(result["packets"])
        window = result["next"]["waiting_on"]
        if window is not None:
            if not expect_condition_window:
                assert "on_condition_imposed" not in window["triggers"], window
                assert all(not r["id"].endswith("_slippery") for r in window["reactions"]), window
            elif "on_condition_imposed" in window["triggers"]:
                return packets, window
        state = harness.sd.combat_state
        assert state is not None
        if state.round_number != round_number:
            assert not expect_condition_window, "Entomb finished without an on_condition_imposed window"
            return packets, None
    raise AssertionError("round did not finish")


def chamber_for(state: CombatState, victim: str) -> str:
    assert state.spatial is not None
    (chamber,) = state.spatial["chambers"]
    assert state.spatial["chambers"][chamber] == {"target_id": victim}
    player = state.get_participant(victim)
    assert player is not None
    assert {"type": "restrained", "duration": None, "source": chamber, "stacks": 1} in player.conditions
    return chamber


async def stamina(victim: str) -> int:
    row = await db_queries.get_player(victim)
    assert row is not None
    return row["stamina"]["current"]


@pytest.mark.parametrize(
    "fight,ability_id,take",
    [
        pytest.param(("rogue", "Entomb"), "rogue_slippery", True, id="rogue-takes"),
        pytest.param(("spy", "Entomb"), "spy_slippery", True, id="spy-takes"),
        pytest.param(("rogue", "Entomb"), "rogue_slippery", False, id="rogue-declines"),
    ],
    indirect=["fight"],
)
async def test_entomb_slippery(fight: Fight, ability_id: str, take: bool) -> None:
    harness, owner, victim, action = fight
    state = await harness.reload()
    player = state.get_participant(victim)
    assert player is not None
    player.conditions = apply_condition(player.conditions, "prone", source="earlier fall", duration=None)
    (prior_condition,) = player.conditions
    await harness.persist()
    before_stamina = await stamina(victim)
    await declare(harness, owner, victim, action)

    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)) as save,
        patch("combat_recharge.roll", return_value=SimpleNamespace(total=5)),
    ):
        packets, window = await advance(harness, expect_condition_window=True)
        assert window is not None
        assert (window["action"], window["actor_id"], window["target_id"]) == (action, owner, victim)
        assert window["stage"] == "post_roll" and window["triggers"] == ["on_condition_imposed"]
        assert {(r["actor_id"], r["id"]) for r in window["reactions"]} == {(victim, ability_id)}
        assert not any(p.get("chamber_id") for p in packets)
        state = await harness.reload()
        chamber = chamber_for(state, victim)
        held_seq = state.held_actions[0]["seq"]
        architect = state.get_participant(owner)
        assert architect is not None and architect.action_ledger["entomb"]["remaining"] == 0
        await fresh_session(harness)
        if take:
            await harness.command("activate", {"id": ability_id})
            assert await stamina(victim) == before_stamina - 3
            state = await harness.reload()
            assert state.reactions_available[victim] == {
                "spent": True,
                "ability_id": ability_id,
                "held_seq": held_seq,
                "window_id": window["window_id"],
                "stage": "post_roll",
            }
            await fresh_session(harness)
        else:
            assert await stamina(victim) == before_stamina
        packets, _ = await advance(harness, expect_condition_window=False)

    save.assert_called_once()
    (cast,) = [p for p in packets if p["actor_id"] == owner]
    assert (cast["target_id"], cast["chamber_id"], cast["save_success"]) == (victim, chamber, False)
    assert cast["condition_inflicted"] == "restrained"
    state = await harness.reload()
    architect = state.get_participant(owner)
    player = state.get_participant(victim)
    assert architect is not None and architect.action_ledger["entomb"]["remaining"] == 0
    assert player is not None and prior_condition in player.conditions
    reactions = [p for p in packets if p.get("declaration_type") == "reaction"]
    next_strike = {"declarations": [strike(owner, victim, "Geometry Strike")]}
    if take:
        (receipt,) = reactions
        assert (receipt["ability_id"], receipt["actor_id"], receipt["against_actor_id"], receipt["window_id"]) == (
            ability_id,
            victim,
            owner,
            window["window_id"],
        )
        assert (receipt["mechanical_effect"], receipt["chamber_id"]) == ("restraint_escaped", chamber)
        assert packets.index(receipt) < packets.index(cast)
        assert state.spatial is not None and not state.spatial["chambers"]
        assert player.conditions == [prior_condition]
        wall = state.get_participant(chamber)
        assert wall is not None and wall.hp_current == 0 and wall.is_dead
        facts = await harness.command("query_info", {"kind": "combat"})
        assert "chambers" not in facts and chamber not in facts["positions"]
        await harness.command("declare_phase", next_strike)
    else:
        assert reactions == [] and chamber_for(state, victim) == chamber
        assert await stamina(victim) == before_stamina
        assert "chamber" in await harness.command("declare_phase", next_strike, error=True)


@pytest.mark.parametrize(
    "fight,face,protection,condition",
    [
        pytest.param(("rogue", "Shield Bash"), 1, None, "prone", id="prone"),
        pytest.param(("rogue", "Entomb"), 20, None, None, id="save"),
        pytest.param(("rogue", "Entomb"), 1, "immune", None, id="immune"),
        pytest.param(("rogue", "Entomb"), 1, "spent", "restrained", id="already-reacted"),
    ],
    indirect=["fight"],
)
async def test_no_slippery_without_imposed_restraint_and_reaction(
    fight: Fight, face: int, protection: str | None, condition: str | None
) -> None:
    harness, actor, victim, action = fight
    if protection is not None:
        state = await harness.reload()
        if protection == "immune":
            player = state.get_participant(victim)
            assert player is not None
            player.condition_immunities = {"restrained": "test protection"}
        else:
            state.reactions_available[victim] = reaction_spend.spend(
                "rogue_uncanny_dodge", {"id": "earlier-hit", "stage": "post_roll"}, held_seq=-1
            )
        await harness.persist()
    before_stamina = await stamina(victim)
    await declare(harness, actor, victim, action)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(face)) as save,
        patch("combat_recharge.roll", return_value=SimpleNamespace(total=5)),
    ):
        packets, _ = await advance(harness, expect_condition_window=False)
    save.assert_called_once()
    (cast,) = [p for p in packets if p["actor_id"] == actor and "save_success" in p]
    assert cast["save_success"] is (face == 20)
    assert cast.get("condition_inflicted") == condition
    assert not any(p.get("declaration_type") == "reaction" for p in packets)
    assert await stamina(victim) == before_stamina
