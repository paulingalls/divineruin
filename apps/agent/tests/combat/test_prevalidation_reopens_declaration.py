import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _damage_resolver, _fake_db_mod
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import character_spells
import combat_phase
import combat_turn
import db_mutations
import db_queries
from session_data import CombatParticipant, CombatState


def _state(combat_id: str, player_id: str, action: str) -> CombatState:
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
                id="reset_foe",
                name="Ogre",
                type="enemy",
                initiative=10,
                hp_current=20,
                hp_max=20,
                ac=13,
            ),
        ],
        initiative_order=[player_id, "reset_foe"],
        beat="resolution",
        pending_declarations={player_id: {"type": "ability", "action": action, "target_id": "reset_foe"}},
    )


async def _seed(pool, player_id: str) -> None:
    data = {
        "player_id": player_id,
        "name": "Brann",
        "class": "warrior",
        "level": 8,
        "hp": {"current": 25, "max": 25},
        "stamina": {"current": 10, "max": 10},
        "focus": {"current": 0, "max": 10},
    }
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(data),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("suffix", "action", "cause"),
    [
        ("unowned", "warrior_unstoppable_charge", "hasn't learned Unstoppable Charge"),
        ("unknown", "invented_ability", "Unknown spell"),
        ("unaffordable", "arcane_shield_spell", "Not enough Focus"),
    ],
)
async def test_prevalidation_refusal_reopens_persisted_phase_and_allows_retry(dev_db_pool, suffix, action, cause):
    pool = dev_db_pool
    player_id = f"s051_reset_{suffix}"
    combat_id = f"combat_s051_reset_{suffix}"
    try:
        await _seed(pool, player_id)
        if action == "arcane_shield_spell":
            await character_spells.record_learned(player_id, action, "discovery", conn=pool)
        state = _state(combat_id, player_id, action)
        await db_mutations.save_combat_state(combat_id, state.to_dict(), conn=pool)
        context = make_context(player_id=player_id)
        context.userdata.combat_state = state

        with pytest.raises(ToolError) as refused:
            await combat_turn._resolve_phase_impl(context, resolver=_damage_resolver(0))

        message = str(refused.value)
        assert cause in message
        assert "whole phase" in message
        assert context.userdata.combat_state.beat == combat_phase.PhaseBeat.DECLARATION
        assert context.userdata.combat_state.pending_declarations == {}
        persisted = await db_mutations.load_combat_state(combat_id, conn=pool)
        assert persisted is not None
        assert persisted.beat == combat_phase.PhaseBeat.DECLARATION
        assert persisted.pending_declarations == {}
        row = await db_queries.get_player(player_id, conn=pool)
        assert row is not None
        assert row["hp"]["current"] == 25
        assert row["stamina"]["current"] == 10
        assert row["focus"]["current"] == 0
        assert all(not participant.conditions for participant in persisted.participants)

        await combat_turn._declare_phase_impl(context, {player_id: {"type": "defend"}})
        result = await combat_turn._resolve_phase_impl(context, resolver=_damage_resolver(0))
        assert isinstance(result, str)
        assert json.loads(result)["packets"][0]["resolved"] is True
    finally:
        await db_mutations.delete_combat_state(combat_id, conn=pool)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


@pytest.mark.asyncio
async def test_malformed_stored_declaration_reopens_and_allows_retry(dev_db_pool):
    pool = dev_db_pool
    player_id = "s060_malformed"
    combat_id = "combat_s060_malformed"
    try:
        await _seed(pool, player_id)
        state = _state(combat_id, player_id, "Longsword")
        state.pending_declarations[player_id] = {"type": "attack", "action": "Longsword"}
        await db_mutations.save_combat_state(combat_id, state.to_dict(), conn=pool)
        context = make_context(player_id=player_id)
        context.userdata.combat_state = state

        with pytest.raises(ToolError) as refused:
            await combat_turn._resolve_phase_impl(context, resolver=_damage_resolver(0))

        message = str(refused.value)
        session_beat = context.userdata.combat_state.beat
        session_pending = context.userdata.combat_state.pending_declarations
        persisted = await db_mutations.load_combat_state(combat_id, conn=pool)
        assert persisted is not None
        row = await db_queries.get_player(player_id, conn=pool)
        assert row is not None

        await combat_turn._declare_phase_impl(context, {player_id: {"type": "defend"}})

        assert "attack declaration requires a 'target_id'" in message
        assert "whole phase" in message
        assert session_beat == combat_phase.PhaseBeat.DECLARATION
        assert session_pending == {}
        assert persisted.beat == combat_phase.PhaseBeat.DECLARATION
        assert persisted.pending_declarations == {}
        assert row["hp"]["current"] == 25
        assert row["stamina"]["current"] == 10
        assert row["focus"]["current"] == 0
        assert all(not participant.conditions for participant in persisted.participants)

        result = await combat_turn._resolve_phase_impl(context, resolver=_damage_resolver(0))
        assert isinstance(result, str)
        assert json.loads(result)["packets"][0]["resolved"] is True
    finally:
        await db_mutations.delete_combat_state(combat_id, conn=pool)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


def test_reopen_helper_is_pure_and_changes_only_declaration_fields():
    original = _state("combat_reset_pure", "reset_pure", "invented_ability")

    reopened = combat_phase.reopen_declaration(original)

    assert reopened is not original
    assert original.beat == combat_phase.PhaseBeat.RESOLUTION
    assert original.pending_declarations
    assert reopened.beat == combat_phase.PhaseBeat.DECLARATION
    assert reopened.pending_declarations == {}
    assert reopened.participants == original.participants
    assert reopened.round_number == original.round_number


@pytest.mark.asyncio
async def test_recovery_write_failure_does_not_replace_session_state():
    state = _state("combat_reset_failure", "reset_failure", "invented_ability")
    context = make_context(player_id="reset_failure")
    context.userdata.combat_state = state
    queries = MagicMock(
        get_player=AsyncMock(
            return_value={
                "player_id": "reset_failure",
                "class": "warrior",
                "level": 8,
                "focus": {"current": 0, "max": 10},
            }
        )
    )
    mutations = MagicMock(save_combat_state=AsyncMock(side_effect=RuntimeError("recovery failed")))

    with pytest.raises(RuntimeError, match="recovery failed"):
        await combat_turn._resolve_phase_impl(
            context,
            queries=queries,
            mutations=mutations,
            db_mod=_fake_db_mod(),
            resolver=_damage_resolver(0),
            character_spells_mod=MagicMock(get_known=AsyncMock(return_value=[])),
        )

    assert context.userdata.combat_state is state
    assert state.beat == combat_phase.PhaseBeat.RESOLUTION


@pytest.mark.asyncio
async def test_packet_tool_error_after_prevalidation_does_not_reopen(monkeypatch):
    state = _state("combat_reset_late", "reset_late", "invented_ability")
    state.pending_declarations = {"reset_late": {"type": "defend"}}
    context = make_context(player_id="reset_late")
    context.userdata.combat_state = state
    mutations = MagicMock(save_combat_state=AsyncMock())
    monkeypatch.setattr(combat_turn, "_resolve_one_packet", AsyncMock(side_effect=ToolError("packet failed")))

    with pytest.raises(ToolError, match="packet failed"):
        await combat_turn._resolve_phase_impl(
            context,
            mutations=mutations,
            db_mod=_fake_db_mod(),
            resolver=_damage_resolver(0),
        )

    assert context.userdata.combat_state is state
    assert state.beat == combat_phase.PhaseBeat.RESOLUTION
    assert state.pending_declarations
    mutations.save_combat_state.assert_not_awaited()
