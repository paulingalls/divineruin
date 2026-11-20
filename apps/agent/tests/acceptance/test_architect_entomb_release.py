from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.test_architect_entomb import fight as fight
from acceptance.test_architect_entomb import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_entomb import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_architect_entomb import seal, strike
from acceptance.test_architect_fight import enter, pos, reopen

import db_mutations
from combat_state import CombatState
from combat_structures import add_wall
from conditions import apply_condition
from declarations import ManeuverIntent


def escape(victim, chamber):
    return {"reshape": [], "kind": "maneuver", "actor_id": victim, "target_id": chamber}


async def cleared(fight, victim, chamber):
    state = await fight.reload()
    assert state.get_participant(chamber).is_dead
    assert state.get_participant(chamber).hp_current == 0
    assert all(c.get("source") != chamber for c in state.get_participant(victim).conditions)
    facts = await fight.command("query_info", {"kind": "combat"})
    assert "chambers" not in facts
    assert chamber not in facts["positions"]
    assert all(chamber not in line for line in facts["spoken"])


async def test_entomb_escape_uses_strength_after_reload(fight):
    owner, victim, chamber = await seal(fight)
    for strength, face, total, expected in ((8, 19, 18, "failed"), (20, 15, 20, "escaped")):
        state = await fight.reload()
        state.get_participant(victim).attributes.update(strength=strength, dexterity=20)
        await fight.persist()
        await fight.command("declare_phase", {"declarations": [escape(victim, chamber)]})
        assert (await fight.reload()).pending_declarations[victim]["maneuver_intent"] == ManeuverIntent.ESCAPE
        with (
            patch("combat_maneuver.random", SimpleNamespace(randint=lambda *_, rolled=face: rolled)),
            patch("combat_turn_start.dice_roll", return_value=SimpleNamespace(total=3)),
        ):
            result = next(p for p in await fight.drain() if p["actor_id"] == victim)
        assert (result["escape_total"], result["escape_dc"], result["escape"]) == (total, 20, expected)
        if expected == "failed":
            assert (await fight.reload()).spatial["chambers"] == {chamber: {"target_id": victim}}
    await cleared(fight, victim, chamber)
    await fight.command("declare_phase", {"declarations": [strike(owner, victim, "Geometry Strike")]})
    with patch("combat_turn_start.dice_roll") as compression, patch("check_resolution.dice_roll", return_value=_d20(1)):
        await fight.drain()
    compression.assert_not_called()


@pytest.mark.parametrize("fight", [((20, 20), None)], indirect=True)
async def test_ally_breaks_chamber_before_pending_escape(fight):
    _, victim, chamber = await seal(fight)
    ally = fight.players[1]
    assert "cannot be maneuvered" in await fight.command(
        "declare_phase", {"declarations": [escape(ally, chamber)]}, error=True
    )
    state = await fight.reload()
    state.get_participant(ally).initiative = 25
    state.get_participant(victim).initiative = 5
    await fight.persist()
    for face, damage, remaining in ((1, 0, 30), (15, 28, 1), (15, 0, 0)):
        declarations = [strike(ally, chamber, "Longsword")]
        if remaining == 0:
            declarations.append(escape(victim, chamber))
        await fight.command("declare_phase", {"declarations": declarations})
        with (
            patch("check_resolution.dice_roll", return_value=_d20(face)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(damage)),
            patch("combat_turn_start.dice_roll", return_value=SimpleNamespace(total=3)) as compression,
            patch("combat_maneuver.random") as roller,
        ):
            packets = await fight.drain()
        result = next(p for p in packets if p["actor_id"] == ally)
        assert result["hit"] is (face != 1)
        assert (await fight.reload()).get_participant(chamber).hp_current == remaining
        if remaining:
            assert (await fight.reload()).spatial["chambers"] == {chamber: {"target_id": victim}}
        else:
            assert next(p for p in packets if p["actor_id"] == victim)["escape"] == "chamber_already_released"
            compression.assert_not_called()
            roller.randint.assert_not_called()
    await cleared(fight, victim, chamber)


async def test_flee_releases_chamber_before_reentry(fight):
    _, victim, chamber = await seal(fight)
    await fight.command("end_combat", {"outcome": "fled"})
    await reopen(fight)
    await enter(fight)
    await cleared(fight, victim, chamber)


@pytest.mark.parametrize("fight", [((20, 20), None)], indirect=True)
async def test_architect_death_collapses_chamber_and_preserves_unrelated_effects(fight, monkeypatch):
    owner, victim, chamber = await seal(fight)
    ally = fight.players[1]
    state = await fight.reload()
    state.get_participant(owner).hp_current = 1
    state.get_participant(ally).initiative = 25
    state.get_participant(victim).initiative = 5
    state.get_participant(victim).conditions = apply_condition(state.get_participant(victim).conditions, "prone")
    add_wall(state, "unrelated", "Unrelated wall", pos(40, 0), pos(40, 20))
    await fight.persist()
    snapshots = []
    save = db_mutations.save_combat_state

    async def capture(combat_id, data, **kwargs):
        await save(combat_id, data, **kwargs)
        if data["architect_encounter"]["phase"] == "destroyed":
            snapshots.append(CombatState.from_dict(data))

    monkeypatch.setattr(db_mutations, "save_combat_state", capture)
    await fight.command("declare_phase", {"declarations": [strike(ally, owner, "Longsword")]})
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        patch("combat_turn_start.dice_roll") as compression,
    ):
        await fight.drain()
    state = snapshots[-1]
    assert state.get_participant(chamber).is_dead
    assert not state.spatial["chambers"] and set(state.spatial["structures"]) == {"unrelated"}
    assert [c["type"] for c in state.get_participant(victim).conditions] == ["prone"]
    assert fight.last_result["outcome"] == "victory"
    compression.assert_not_called()
