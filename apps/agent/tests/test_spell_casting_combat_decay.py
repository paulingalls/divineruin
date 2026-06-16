"""In-combat suppression of cast-paced Resonance decay (M4.1 story-007).

Decision resonance-decay-phase-canonical: the combat PHASE is the canonical
Resonance-decay clock — story-001's wrap beat (combat_phase.advance_combat_phase)
sheds one round per phase. Sprint-017's cast-paced decay (one shed per real cast,
spell_casting._cast_spell_impl) was a pre-combat stopgap. If BOTH fire in combat,
Resonance double-decays. So a cast IN combat must only GENERATE, never shed; the
wrap beat owns decay. Out of combat, cast-paced decay stays exactly as sprint-017.

These tests drive _cast_spell_impl directly with mock db/queries/persistence/
mutations (the test_spell_casting precedent) and the seeded racial-spec stub, and
flip session.combat_state to toggle session.in_combat. The invariant: decay fires
once per context, never both — proven here for the cast path (in-combat suppressed,
out-of-combat unchanged) regardless of race.
"""

import json
from unittest.mock import AsyncMock, MagicMock

from sample_fixtures import make_context, make_db_mod

from session_data import CombatState
from spell_casting import _cast_spell_impl
from spells import Spell, SpellSource, SpellTier

# The seeded human decay_bonus (content/racial_resonance_bonuses.json) the cast reads via
# racial_resonance.get_racial_resonance_modifier. Mirrors test_spell_casting._RACIAL_SPEC.
_RACIAL_SPEC = {
    ("human", "decay_bonus"): 1,
}


def _racial_mod():
    """Stub racial_resonance returning the seeded spec values; raises on any unexpected
    (race, key) so a test fails loud if the cast looks up the wrong modifier."""
    mod = MagicMock()
    mod.get_racial_resonance_modifier = MagicMock(side_effect=lambda race, key: _RACIAL_SPEC[(race, key)])
    return mod


def _combat_state() -> CombatState:
    """A minimal CombatState — its mere presence flips session.in_combat True
    (session_data.py: in_combat == combat_state is not None). The cast path reads
    only the property, never the combat internals, so empty participants suffice."""
    return CombatState(combat_id="combat_1", participants=[], initiative_order=[])


def _player(focus: int = 10, level: int = 5, race: str | None = None) -> dict:
    player = {
        "player_id": "player_1",
        "name": "Lyra",
        "class": "mage",
        "level": level,
        "focus": {"current": focus, "max": 10},
    }
    if race is not None:
        player["race"] = race
    return player


def _spell(
    *,
    spell_id: str = "test_spell",
    source: SpellSource = "arcane",
    tier: SpellTier = "standard",
    focus_cost: int = 3,
    resonance: int = 3,
) -> Spell:
    return Spell(
        id=spell_id,
        name="Test Spell",
        source=source,
        spell_tier=tier,
        focus_cost=focus_cost,
        mechanics="Deals force damage to one target.",
        narration_cue="A surge of raw power snaps outward.",
        audio_cue="SFX-001",
        resonance_by_source={source: resonance},
        terrain_effects={},
        concentration=False,
    )


async def _cast(
    spell: Spell,
    *,
    race: str | None = None,
    start_resonance: int = 0,
    in_combat: bool = False,
):
    """Invoke _cast_spell_impl with mock db/queries/persistence/mutations and the racial
    stub. Sets session.combat_state when in_combat. Returns (packet, ctx, mutations_mock)."""
    ctx = make_context()
    ctx.userdata.resonance.current = start_resonance
    if in_combat:
        ctx.userdata.combat_state = _combat_state()
    mock_db, _conn = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=_player(race=race))
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    mutations = MagicMock()
    mutations.update_player_resonance = AsyncMock()
    events = MagicMock()
    events.publish_resonance_changed = AsyncMock()
    spells_mod = MagicMock()
    spells_mod.get_spell = MagicMock(return_value=spell)
    raw = await _cast_spell_impl(
        ctx,
        spell.id,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        resonance_mutations_mod=mutations,
        resonance_events_mod=events,
        spells_mod=spells_mod,
        racial_mod=_racial_mod(),
    )
    return json.loads(raw), ctx, mutations


class TestInCombatSuppressesCastDecay:
    async def test_in_combat_generates_but_does_not_shed(self):
        # AC1: in combat, a generating cast accrues its Resonance but the cast path does NOT
        # shed. Race-less start 7, generated 3 -> 10 (out of combat would shed 1 -> 9).
        packet, ctx, mutations = await _cast(
            _spell(source="arcane", focus_cost=3, resonance=3), start_resonance=7, in_combat=True
        )
        assert packet["resonance_generated"] == 3
        assert ctx.userdata.resonance.current == 10  # 7 + 3, no decay shed
        # The persisted total is the un-shed sum — the cast path wrote no decay (the wrap beat owns it).
        mutations.update_player_resonance.assert_awaited_once()
        assert mutations.update_player_resonance.call_args.args[1] == 10

    async def test_in_combat_human_does_not_shed(self):
        # AC3: suppression applies regardless of race. A Human in combat (decay_bonus 1) still
        # sheds nothing from the cast — start 7, generated 3 -> 10 (out of combat would be 8).
        packet, ctx, _m = await _cast(
            _spell(source="arcane", focus_cost=3, resonance=3), race="human", start_resonance=7, in_combat=True
        )
        assert packet["resonance_generated"] == 3
        assert ctx.userdata.resonance.current == 10  # 7 + 3, human decay_bonus suppressed in combat


class TestOutOfCombatDecayUnchanged:
    async def test_out_of_combat_race_less_decays_base_one(self):
        # AC2: out of combat, cast-paced decay is exactly sprint-017. Race-less base 1:
        # start 7 -> 6, + 3 generated = 9.
        _packet, ctx, _m = await _cast(
            _spell(source="arcane", focus_cost=3, resonance=3), start_resonance=7, in_combat=False
        )
        assert ctx.userdata.resonance.current == 9

    async def test_out_of_combat_human_decays_two(self):
        # AC2: out of combat a Human sheds base 1 + decay_bonus 1 = 2 before generation:
        # start 7 -> decay(7, +1) = 5, + 3 = 8.
        _packet, ctx, _m = await _cast(
            _spell(source="arcane", focus_cost=3, resonance=3), race="human", start_resonance=7, in_combat=False
        )
        assert ctx.userdata.resonance.current == 8
