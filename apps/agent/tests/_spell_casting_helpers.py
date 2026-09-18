"""Shared fixtures for the spell-casting suites, split out of test_spell_casting.py.

Every ``_cast*`` helper here drives a tool's ``_impl`` directly with a mock RunContext plus
injected mock db/queries/persistence/resonance-mutations mods (the sample_fixtures seam, the
ability_tools precedent) — our own seams only. spells/resonance/leveling run REAL: the
seed_spells autouse fixture in tests/conftest.py supplies the live catalog, and resonance +
cantrip dice are pure. Casts needing a precise focus_cost/source inject a controlled Spell via
a mock spells_mod so the arithmetic is independent of catalog tuning; pass the real module
(TestCastSpellRealCatalog) to exercise the catalog end-to-end.
"""

import json
from unittest.mock import AsyncMock, MagicMock

from sample_fixtures import make_context, make_db_mod

from session_data import CombatState
from spell_casting import _cast_spell_impl
from spells import Spell, SpellSource, SpellTier


def _player(focus: int = 10, level: int = 5) -> dict:
    return {
        "player_id": "player_1",
        "name": "Lyra",
        "class": "mage",
        "level": level,
        "focus": {"current": focus, "max": 10},
    }


def _spell(
    *,
    spell_id: str = "test_spell",
    source: SpellSource = "arcane",
    tier: SpellTier = "standard",
    focus_cost: int = 10,
    name: str = "Test Spell",
    resonance: int = 6,
    concentration: bool = False,
) -> Spell:
    # resonance_by_source carries the designed per-spell Resonance the cast path reads
    # (decision resonance-by-source-ssot); default 6 keeps the canonical "flickering"
    # fixture. Pass resonance= to control it (0 for cantrips, a formula-deviating value
    # to prove the catalog wins). concentration= flags a concentration spell (story-006).
    return Spell(
        id=spell_id,
        name=name,
        source=source,
        spell_tier=tier,
        focus_cost=focus_cost,
        mechanics="Deals force damage to one target.",
        narration_cue="A surge of raw power snaps outward.",
        audio_cue="SFX-001",
        resonance_by_source={source: resonance},
        terrain_effects={},
        concentration=concentration,
    )


def _known(*spell_ids: str):
    module = MagicMock()
    module.get_known = AsyncMock(return_value=[{"spell_id": spell_id} for spell_id in spell_ids])
    return module


async def _cast(
    spell: Spell,
    *,
    focus: int = 10,
    level: int = 5,
    start_resonance: int = 0,
    player: dict | None = None,
    spells_mod=None,
    combat_state: CombatState | None = None,
):
    """Invoke _cast_spell_impl with mock db/queries/persistence/mutations.

    Returns (parsed_packet, ctx, persistence_mock, mutations_mock, events_mock).
    spells_mod defaults to a mock returning `spell`; pass the real module for
    catalog tests. Notably this injects NO ward_resolution_mod, so the cast
    resolves its ward through the production default path; pass combat_state to
    put a scope ward in front of it.
    """
    ctx = make_context()
    ctx.userdata.resonance.current = start_resonance
    ctx.userdata.combat_state = combat_state
    mock_db, _conn = make_db_mod()
    queries = MagicMock()
    _lock_row = player if player is not None else _player(focus, level)
    queries.get_player = AsyncMock(return_value=_lock_row)
    # story-008: the OOC caster row now comes from the id-ordered get_players_for_update batch.
    queries.get_players_for_update = AsyncMock(side_effect=lambda ids, *, conn=None: {i: _lock_row for i in ids})
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    mutations = MagicMock()
    mutations.update_player_resonance = AsyncMock()
    events = MagicMock()
    events.publish_resonance_changed = AsyncMock()
    if spells_mod is None:
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
        character_spells_mod=_known(spell.id),
    )
    return json.loads(raw), ctx, persistence, mutations, events


def _dice_mod(total: int):
    """A dice module whose roll('d20') returns a fixed total (deterministic echo tests)."""
    mod = MagicMock()
    mod.roll = MagicMock(return_value=MagicMock(total=total))
    return mod


async def _cast_echo(
    spell: Spell,
    *,
    focus: int = 10,
    start_resonance: int = 0,
    ward_active: bool = False,
    d20: int = 10,
    combat_state: CombatState | None = None,
):
    """Invoke _cast_spell_impl with the M3.2 echo/ward mods injected.

    veil_ward + hollow_echo run REAL (pure); dice_mod is fixed for a deterministic roll and
    echo_events is mocked to assert the publish without touching game_events.
    Returns (parsed_packet, ctx, echo_events_mock).

    Pass combat_state to resolve the ward through the REAL resolver off that scope; the
    ward_active shortcut injects a stub resolver instead and never reaches it.
    """
    ctx = make_context()
    ctx.userdata.resonance.current = start_resonance
    ctx.userdata.combat_state = combat_state
    # M24: the cast path resolves the ward from the DB, not from any per-caster flag. Inject the
    # resolver so the test states plainly whether a scope ward covers this cast.
    ward_res = MagicMock()
    ward_res.resolve_scope_ward = AsyncMock(
        return_value={"source": "cleric", "expires_at": None, "dismissible": True} if ward_active else None
    )
    mock_db, _conn = make_db_mod()
    queries = MagicMock()
    _lock_row = _player(focus)
    queries.get_player = AsyncMock(return_value=_lock_row)
    queries.get_players_for_update = AsyncMock(side_effect=lambda ids, *, conn=None: {i: _lock_row for i in ids})
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    mutations = MagicMock()
    mutations.update_player_resonance = AsyncMock()
    events = MagicMock()
    events.publish_resonance_changed = AsyncMock()
    echo_events = MagicMock()
    echo_events.publish_hollow_echo = AsyncMock()
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
        dice_mod=_dice_mod(d20),
        echo_events_mod=echo_events,
        character_spells_mod=_known(spell.id),
        # A combat_state test wants the real resolver to read it; injecting a stub would mask it.
        **({} if combat_state is not None else {"ward_resolution_mod": ward_res}),
    )
    return json.loads(raw), ctx, echo_events


# --- M3.4 racial Resonance + concentration wiring (story-006) ---

# The seeded spec values (content/racial_resonance_bonuses.json) the cast path reads via
# racial_resonance.get_racial_resonance_modifier. The stub returns these; the real seeded-table
# lookup is proven by the story-007 real-PG capstone.
_RACIAL_SPEC = {
    ("korath", "primal_reduction"): 1,
    ("thessyn", "flickering_threshold_bonus"): 1,
    ("vaelti", "echo_save_advantage"): True,
    ("human", "decay_bonus"): 1,
}


def _racial_mod():
    """Stub racial_resonance returning the seeded spec values; raises (KeyError) on any
    unexpected (race, key), so a test fails loud if the cast looks up the wrong modifier."""
    mod = MagicMock()
    mod.get_racial_resonance_modifier = MagicMock(side_effect=lambda race, key: _RACIAL_SPEC[(race, key)])
    return mod


def _dice_seq(*totals: int):
    """A dice module whose successive roll('d20') calls return totals in order — lets the
    Vaelti advantage test control BOTH the base roll and the advantage roll."""
    mod = MagicMock()
    mod.roll = MagicMock(side_effect=[MagicMock(total=t) for t in totals])
    return mod


async def _cast_racial(
    spell: Spell,
    *,
    race: str | None = None,
    focus: int = 10,
    level: int = 5,
    start_resonance: int = 0,
    start_flickering_bonus: int = 0,
    start_concentration: str | None = None,
    d20s: tuple[int, ...] = (10,),
    vaelti_warning=None,
    caster_id: str | None = None,
    party_member_ids: list[str] | None = None,
):
    """Invoke _cast_spell_impl with the M3.4 racial + concentration mods injected.

    racial_mod is the seeded-spec stub; concentration_mutations_mod is mocked so the persist is
    asserted without touching the DB; dice_mod is a fixed sequence for deterministic echo rolls.
    ``caster_id``/``party_member_ids`` (story-003) drive a non-primary caster through the same
    entry as the public tool, so the post-commit sync lands on that member, not the primary.
    Returns (parsed_packet, ctx, mutations_mock, concentration_mock, echo_events_mock).
    """
    ctx = make_context(party_member_ids=party_member_ids)
    ctx.userdata.resonance.current = start_resonance
    ctx.userdata.resonance.flickering_bonus = start_flickering_bonus
    ctx.userdata.concentration.spell_id = start_concentration
    mock_db, _conn = make_db_mod()
    player = _player(focus, level)
    if race is not None:
        player["race"] = race
    if caster_id is not None:
        player["player_id"] = caster_id
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=player)
    queries.get_players_for_update = AsyncMock(side_effect=lambda ids, *, conn=None: {i: player for i in ids})
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    mutations = MagicMock()
    mutations.update_player_resonance = AsyncMock()
    events = MagicMock()
    events.publish_resonance_changed = AsyncMock()
    echo_events = MagicMock()
    echo_events.publish_hollow_echo = AsyncMock()
    concentration = MagicMock()
    concentration.update_player_concentration = AsyncMock()
    spells_mod = MagicMock()
    spells_mod.get_spell = MagicMock(return_value=spell)
    raw = await _cast_spell_impl(
        ctx,
        spell.id,
        caster_id=caster_id,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        resonance_mutations_mod=mutations,
        resonance_events_mod=events,
        spells_mod=spells_mod,
        dice_mod=_dice_seq(*d20s),
        echo_events_mod=echo_events,
        racial_mod=_racial_mod(),
        vaelti_warning_mod=vaelti_warning or MagicMock(),
        concentration_mutations_mod=concentration,
        character_spells_mod=_known(spell.id),
    )
    return json.loads(raw), ctx, mutations, concentration, echo_events
