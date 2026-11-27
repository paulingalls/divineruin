"""Wild Shape casting and exit through the registered combat tools."""

import pytest
from acceptance._capstone_helpers import _d20
from acceptance.mawling_harness import MawlingHarness
from acceptance.seeds import seed_known_spells
from acceptance.test_wild_shape import ABILITY, declare, enter, prepare, updates
from acceptance.test_wild_shape import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_wild_shape import walk as walk
from livekit.agents.llm import FunctionTool
from livekit.agents.llm.utils import build_strict_openai_schema
from sample_fixtures import FixedRng, published_payloads

import db_queries
import event_types

FORM = "grey_wolf"
CAPTAIN = "bandit_captain"
CANTRIP = "primal_thorn_whip"
MINOR = "primal_healing_touch"
MAJOR = "primal_blight"
DISMISS = "dismiss_wild_shape"


async def shifted(walk: MawlingHarness, level: int = 5) -> tuple[str, int]:
    pid = await prepare(walk, "druid", level, focus=10, stamina=6)
    if level == 20:
        await seed_known_spells(walk.pool, pid, (MAJOR,))
        await walk.pool.execute(
            "UPDATE character_spells SET is_prepared=TRUE WHERE player_id=$1 AND spell_id=$2", pid, MAJOR
        )
    await enter(walk)
    state = await walk.reload()
    actor = state.get_participant(pid)
    assert actor is not None
    await declare(walk, ABILITY, FORM)
    await walk.drain()
    transformed = (await walk.reload()).get_participant(pid)
    assert transformed is not None and transformed.wild_shape is not None and transformed.ac != actor.ac
    return pid, actor.ac


async def player_declaration(walk: MawlingHarness, decl: dict, *, error: bool = False) -> dict | str:
    state = await walk.reload()
    return await walk.command(
        "declare_phase",
        {
            "declarations": [
                decl,
                *(
                    {"kind": "defend", "actor_id": p.id, "reshape": []}
                    for p in state.participants
                    if p.id != decl["actor_id"]
                ),
            ]
        },
        error=error,
    )


def cast_spell(pid: str, spell_id: str) -> dict:
    return {
        "kind": "ability",
        "actor_id": pid,
        "action": spell_id,
        "targets": [pid if spell_id == MINOR else CAPTAIN],
        "argument_type": "",
        "reshape": [],
    }


@pytest.mark.parametrize(("level", "spell_id"), [(5, MINOR), (5, CANTRIP), (10, MINOR)])
async def test_form_refuses_spell(walk: MawlingHarness, level: int, spell_id: str) -> None:
    pid, _ = await shifted(walk, level)
    before, packets = await walk.snapshot(), updates(walk)
    error = await player_declaration(walk, cast_spell(pid, spell_id), error=True)
    assert "Wild Shape" in error and f"level {10 if level == 5 else 20}" in error
    assert await walk.snapshot() == before and updates(walk) == packets


async def test_form_refuses_direct_activation(walk: MawlingHarness) -> None:
    await shifted(walk)
    before, packets = await walk.snapshot(), updates(walk)
    error = await walk.command("activate", {"id": CANTRIP, "target_id": CAPTAIN}, error=True)
    assert "Wild Shape" in error and "level 10" in error
    assert await walk.snapshot() == before and updates(walk) == packets


@pytest.mark.parametrize(("level", "spell_id", "cost"), [(5, CANTRIP, 0), (10, CANTRIP, 0), (20, MAJOR, 5)])
async def test_eligible_spell_lands(
    walk: MawlingHarness, monkeypatch: pytest.MonkeyPatch, level: int, spell_id: str, cost: int
) -> None:
    if level == 5:
        pid = await prepare(walk, "druid", focus=10, stamina=6)
        await enter(walk)
    else:
        pid, _ = await shifted(walk, level)
    state, [before] = await walk.snapshot()
    assert before is not None
    captain = next(p for p in state["participants"] if p["id"] == CAPTAIN)
    await player_declaration(walk, cast_spell(pid, spell_id))
    monkeypatch.setattr("check_resolution.dice_roll", lambda *_, **__: _d20(19))
    monkeypatch.setattr("dice.random.SystemRandom", lambda: FixedRng(3))
    result = await walk.command("resolve_phase", {})
    packet = next(p for p in result["packets"] if p["actor_id"] == pid)
    damage = packet["cast"]["damage_result"]["damage"]
    landed = (await walk.reload()).get_participant(CAPTAIN)
    assert damage > 0 and landed is not None and landed.hp_current == max(0, captain["hp_current"] - damage)
    after = await db_queries.get_player(pid)
    assert after is not None and after["focus"]["current"] == before["focus"]["current"] - cost


async def test_dismiss_restores_own_shape(walk: MawlingHarness) -> None:
    pid, ac = await shifted(walk)
    _, [before] = await walk.snapshot()
    assert before is not None
    await player_declaration(walk, {"kind": "interact", "actor_id": pid, "action": DISMISS})
    result = await walk.command("resolve_phase", {})
    actor = (await walk.reload()).get_participant(pid)
    assert actor is not None and actor.wild_shape is None and actor.ac == ac
    after = await db_queries.get_player(pid)
    assert after is not None and all(after[key] == before[key] for key in ("hp", "focus", "stamina"))
    packet = next(p for p in result["packets"] if p["actor_id"] == pid)
    fact = {"actor_id": pid, "form_id": FORM, "reason": "dismissed"}
    assert packet["resolved"] and packet["wild_shape_ended"] == [fact]
    event = updates(walk)[-1]
    assert event["wild_shape_ended"] == [fact]
    assert "wildShape" not in next(p for p in event["combatants"] if p["id"] == pid)

    tool = next(
        tool
        for tool in walk.session.current_agent.tools
        if isinstance(tool, FunctionTool) and tool.info.name == "declare_phase"
    )
    schema = build_strict_openai_schema(tool)["function"]["parameters"]
    assert DISMISS in schema["$defs"]["InteractDecl"]["properties"]["action"]["description"]


async def test_own_shape_cannot_dismiss(walk: MawlingHarness) -> None:
    pid = await prepare(walk, "druid")
    await enter(walk)
    before = await walk.snapshot()
    error = await player_declaration(walk, {"kind": "interact", "actor_id": pid, "action": DISMISS}, error=True)
    assert "Wild Shape" in error
    assert await walk.snapshot() == before


async def test_dismiss_rejects_target_selector(walk: MawlingHarness) -> None:
    pid, _ = await shifted(walk)
    before = await walk.snapshot()
    error = await player_declaration(
        walk, {"kind": "interact", "actor_id": pid, "action": DISMISS, "target_id": CAPTAIN}, error=True
    )
    assert "Wild Shape dismissal takes no target selectors" in error
    assert await walk.snapshot() == before


async def test_end_discards_form_before_next_encounter(walk: MawlingHarness) -> None:
    pid, ac = await shifted(walk)
    old_id = (await walk.reload()).combat_id
    receipt = await walk.command("end_combat", {"outcome": "fled"})
    assert walk.sd.combat_state is None
    assert not await walk.pool.fetchval("SELECT 1 FROM combat_instances WHERE combat_id=$1", old_id)
    row = await db_queries.get_player(pid)
    assert row is not None and "wild_shape" not in row
    await enter(walk)
    actor = (await walk.reload()).get_participant(pid)
    assert actor is not None and actor.wild_shape is None and actor.ac == ac
    (event,) = [event for event in published_payloads(walk.sd.room) if event["type"] == event_types.COMBAT_ENDED]
    fact = {"actor_id": pid, "form_id": FORM, "reason": "combat_ended"}
    assert receipt["wild_shape_ended"] == event["wild_shape_ended"] == [fact]
