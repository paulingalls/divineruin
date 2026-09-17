import json
from unittest.mock import patch

import pytest
from combat._helpers import _damage_resolver
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import ability_persistence
import combat_turn
import conditions
import db_mutations
import db_queries
import mentor_variants
from check_resolution_save import SavingThrowResult
from combat_ability_gate import declared_ability
from session_data import CombatParticipant, CombatState

_BASE = "warrior_unstoppable_charge"
_KELDARAN = "warrior_unstoppable_charge_keldaran"
_THORNWARDEN = "warrior_unstoppable_charge_thornwarden"


def _state(combat_id: str, player_id: str) -> CombatState:
    return CombatState(
        combat_id=combat_id,
        participants=[
            CombatParticipant(
                id=player_id,
                name="Brann",
                type="player",
                initiative=15,
                hp_current=25,
                hp_max=25,
                ac=14,
                level=8,
            ),
            CombatParticipant(
                id="variant_foe",
                name="Ogre",
                type="enemy",
                initiative=10,
                hp_current=20,
                hp_max=20,
                ac=13,
            ),
        ],
        initiative_order=[player_id, "variant_foe"],
        beat="resolution",
        pending_declarations={player_id: {"type": "ability", "action": _KELDARAN, "target_id": "variant_foe"}},
    )


def _failed_save() -> SavingThrowResult:
    return SavingThrowResult(
        save_type="strength",
        roll=5,
        modifier=0,
        total=5,
        dc=13,
        success=False,
        margin=-8,
        effect_applied="prone",
        narrative_hint="",
    )


async def _seed(pool, player_id: str, active_variant: str) -> None:
    data = {
        "player_id": player_id,
        "name": "Brann",
        "class": "warrior",
        "level": 8,
        "hp": {"current": 25, "max": 25},
        "stamina": {"current": 3, "max": 10},
        "focus": {"current": 1, "max": 10},
    }
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(data),
    )
    await ability_persistence.set_elective_equipped(player_id, _BASE, True, conn=pool)
    await ability_persistence.set_active_variant(player_id, _BASE, active_variant, conn=pool)


async def _cleanup(pool, combat_id: str, player_id: str) -> None:
    await db_mutations.delete_combat_state(combat_id, conn=pool)
    await pool.execute("DELETE FROM character_active_variants WHERE player_id = $1", player_id)
    await pool.execute("DELETE FROM character_abilities WHERE player_id = $1", player_id)
    await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


def test_declared_ability_resolves_catalog_namespaces():
    base = declared_ability(_BASE)
    assert base is not None and base[0].id == _BASE and base[1] is None

    variant = declared_ability(_KELDARAN)
    assert variant is not None and variant[0].id == _BASE
    assert variant[1] is not None and variant[1].id == _KELDARAN

    assert declared_ability("arcane_bolt") is None
    assert declared_ability("de_escalate") is None
    assert declared_ability("invented_ability") is None


@pytest.mark.asyncio
async def test_active_variant_uses_base_mechanics_variant_cost_and_metadata(dev_db_pool):
    pool = dev_db_pool
    player_id = "s051_variant_active"
    combat_id = "combat_s051_variant_active"
    try:
        await _seed(pool, player_id, _KELDARAN)
        state = _state(combat_id, player_id)
        await db_mutations.save_combat_state(combat_id, state.to_dict(), conn=pool)
        context = make_context(player_id=player_id)
        context.userdata.combat_state = state

        with patch("check_resolution_save.roll_participant_save", return_value=_failed_save()):
            result = await combat_turn._resolve_phase_impl(context, resolver=_damage_resolver(0))

        assert isinstance(result, str)
        packet = json.loads(result)["packets"][0]
        foe = context.userdata.combat_state.get_participant("variant_foe")
        assert foe is not None
        assert conditions.has_condition(foe.conditions, "prone")
        row = await db_queries.get_player(player_id, conn=pool)
        assert row is not None
        assert row["stamina"]["current"] == 0
        assert row["focus"]["current"] == 0
        assert packet["action"] == _BASE
        assert packet["variant_id"] == _KELDARAN
        assert packet["cultural_attribution"] == mentor_variants.get_mentor_variant(_KELDARAN).cultural_attribution
    finally:
        await _cleanup(pool, combat_id, player_id)


@pytest.mark.asyncio
async def test_inactive_variant_refuses_without_mechanical_write(dev_db_pool):
    pool = dev_db_pool
    player_id = "s051_variant_inactive"
    combat_id = "combat_s051_variant_inactive"
    try:
        await _seed(pool, player_id, _THORNWARDEN)
        state = _state(combat_id, player_id)
        await db_mutations.save_combat_state(combat_id, state.to_dict(), conn=pool)
        context = make_context(player_id=player_id)
        context.userdata.combat_state = state

        with (
            patch("check_resolution_save.roll_participant_save") as save,
            pytest.raises(ToolError, match=f"{_KELDARAN} is not your active variant"),
        ):
            await combat_turn._resolve_phase_impl(context, resolver=_damage_resolver(0))

        row = await db_queries.get_player(player_id, conn=pool)
        assert row is not None
        assert row["stamina"]["current"] == 3
        assert row["focus"]["current"] == 1
        foe = context.userdata.combat_state.get_participant("variant_foe")
        assert foe is not None
        assert not foe.conditions
        save.assert_not_called()
    finally:
        await _cleanup(pool, combat_id, player_id)
