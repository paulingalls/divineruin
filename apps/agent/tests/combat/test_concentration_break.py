"""E2E: per-member concentration break through the real phase loop (M18 story-004, AC #4).

The unit-level coverage in ../test_concentration_break.py drives break_concentration_on_damage
directly with mock DI. This file drives the REAL phase loop (_resolve_phase_impl) with the real
concentration_break module wired in (no mock), for a 2-PC combat where the NON-primary caster is
hit hard enough to incapacitate — proving the break resolves against that caster's own spell
end-to-end, and the primary's own (different) concentration survives untouched.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _damage_resolver, _fake_db_mod
from sample_fixtures import make_context

import concentration_break
from combat_turn import _resolve_phase_impl
from session_data import CombatParticipant, CombatState


def _real_break_with_stubbed_persist():
    """A concentration_break_mod stand-in that runs the REAL break_concentration_on_damage (so the
    per-member resolution under test — session.member_state(damaged_player_id) — executes for
    real) but stubs its DB persist: this is a fast-lane test, not a DB integration test."""
    mod = MagicMock()

    async def _break(*args, **kwargs):
        kwargs.setdefault("concentration_mutations", MagicMock(update_player_concentration=AsyncMock()))
        return await concentration_break.break_concentration_on_damage(*args, **kwargs)

    mod.break_concentration_on_damage = AsyncMock(side_effect=_break)
    return mod


def _two_pc_incapacitating_state() -> CombatState:
    """2 players + 1 enemy at RESOLUTION: both players attack the enemy; the enemy attacks the
    NON-primary player_2 (low HP) for a fixed 15 damage (>= the AC #4 threshold), dropping them to
    0 HP — incapacitated, so their concentration auto-breaks without needing a controlled dice roll.
    player_1 (primary) is never targeted this phase, so their own concentration must survive."""
    return CombatState(
        combat_id="combat_concentration_mp",
        participants=[
            CombatParticipant(
                id="player_1",
                name="player_1",
                type="player",
                initiative=20,
                hp_current=25,
                hp_max=25,
                ac=14,
                action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
            ),
            CombatParticipant(
                id="player_2",
                name="player_2",
                type="player",
                initiative=15,
                hp_current=12,
                hp_max=25,
                ac=14,
                action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
            ),
            CombatParticipant(
                id="goblin_1",
                name="Goblin",
                type="enemy",
                initiative=1,
                hp_current=100,
                hp_max=100,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": ["light"]}],
                xp_value=50,
            ),
        ],
        initiative_order=["player_1", "player_2", "goblin_1"],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
        beat="resolution",
        pending_declarations={
            "player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_1"},
            "player_2": {"type": "attack", "action": "Longsword", "target_id": "goblin_1"},
            "goblin_1": {"type": "attack", "action": "Scimitar", "target_id": "player_2"},
        },
    )


class TestConcentrationBreakE2E:
    @pytest.mark.asyncio
    async def test_non_primary_hit_breaks_only_their_own_spell(self):
        ctx = make_context(party_member_ids=["player_2"])
        ctx.userdata.concentration.spell_id = "divine_bless"  # primary's own spell
        player_2 = ctx.userdata.party.member("player_2")
        assert player_2 is not None
        player_2.concentration.spell_id = "arcane_fly"  # non-primary's own spell
        ctx.userdata.combat_state = _two_pc_incapacitating_state()

        mutations_mod = MagicMock()
        mutations_mod.update_player_hp = AsyncMock()
        mutations_mod.save_combat_state = AsyncMock()
        mutations_mod.delete_combat_state = AsyncMock()
        queries_mod = MagicMock()
        queries_mod.get_player_inventory = AsyncMock(return_value=[])
        resonance_mutations = MagicMock()
        resonance_mutations.update_player_resonance = AsyncMock()
        resonance_events_mod = MagicMock()
        resonance_events_mod.publish_resonance_changed = AsyncMock()

        raw = await _resolve_phase_impl(
            ctx,
            mutations=mutations_mod,
            queries=queries_mod,
            resolver=_damage_resolver(15),
            concentration_break_mod=_real_break_with_stubbed_persist(),
            resonance_mutations=resonance_mutations,
            resonance_events_mod=resonance_events_mod,
            db_mod=_fake_db_mod(),
        )

        assert isinstance(raw, str)  # combat continues -> JSON, not the end-of-combat tuple
        packets = {p["actor_id"]: p for p in json.loads(raw)["packets"]}

        # Only player_2's spell broke and was surfaced; player_1's is untouched.
        assert packets["goblin_1"]["concentration_broken"] == "arcane_fly"
        assert player_2.concentration.spell_id is None
        assert ctx.userdata.concentration.spell_id == "divine_bless"
