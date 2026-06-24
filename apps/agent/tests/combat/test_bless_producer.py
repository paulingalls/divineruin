"""M4.8 story-004: Bless spell producer — apply Blessed on cast.

Stories 001-003 built the CONSUMER side (BonusDie model, +1d4 fold, consume-on-roll). This
story is the PRODUCER: a spell whose catalog row carries a structured `applies_condition`
lands that condition on the cast's target. Single-target (multi-target is story-007). Both
paths wired (customer decision story-004-in-combat-scope):

- A) catalog schema: Spell.applies_condition, parsed + fail-loud validated against the
     condition catalog.
- B) out-of-combat producer: _resolve_cast applies + persists the condition to the target's
     players.data SSOT (gated on not session.in_combat) and surfaces it in the cast packet.
- C) in-combat producer: _resolve_one_packet applies the produced condition to the target
     CombatParticipant on the working state (rides save_combat_state).
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import make_context, make_db_mod

import conditions
import spell_casting
from spells import Spell, parse_spell_row

# A divine_bless-shaped catalog row carrying the new structured producer field. Mirrors the
# strict M3.3 row shape (resonance_by_source/terrain_effects/audio_cue/concentration required).
_BLESS_ROW = {
    "id": "divine_bless",
    "name": "Bless",
    "source": "divine",
    "spell_tier": "minor",
    "focus_cost": 2,
    "mechanics": "An ally gains +1d4 on attacks and saves. Concentration.",
    "narration_cue": "You speak their name and your patron hears — warmth settling into bones.",
    "resonance_by_source": {"divine": 1},
    "terrain_effects": {},
    "audio_cue": "",
    "concentration": True,
}


# --- Group A: catalog schema (pure parse) ---


def test_parse_carries_applies_condition():
    spell = parse_spell_row("divine_bless", {**_BLESS_ROW, "applies_condition": "blessed"})
    assert spell.applies_condition == "blessed"


def test_parse_without_applies_condition_defaults_none():
    # Existing spells (no producer field) parse with applies_condition None — no condition produced.
    spell = parse_spell_row(
        "arcane_bolt", {**_BLESS_ROW, "id": "arcane_bolt", "source": "arcane", "resonance_by_source": {"arcane": 0}}
    )
    assert spell.applies_condition is None


def test_parse_unknown_applies_condition_fails_loud():
    # Strict-loader convention: a typo'd / unknown condition type fails at parse, naming the row.
    with pytest.raises(ValueError, match="applies_condition"):
        parse_spell_row("divine_bless", {**_BLESS_ROW, "applies_condition": "not_a_condition"})


# --- Group B: out-of-combat producer (mock-conn) ---


def _bless_spell(applies_condition: str | None = "blessed") -> Spell:
    """A free (focus 0, resonance 0) divine spell so the cast resolves past the Focus/Resonance
    gates with no side-effects but the producer hook — only applies_condition matters here."""
    return Spell(
        id="divine_bless",
        name="Bless",
        source="divine",
        spell_tier="minor",
        focus_cost=0,
        mechanics="An ally gains +1d4 on attacks and saves.",
        narration_cue="Warmth settling into bones.",
        audio_cue="",
        resonance_by_source={"divine": 0},
        terrain_effects={},
        concentration=False,
        applies_condition=applies_condition,
    )


def _caster(player_id: str = "caster_1", conditions_list: list | None = None) -> dict:
    return {
        "player_id": player_id,
        "name": "Caster",
        "class": "cleric",
        "level": 5,
        "focus": {"current": 10, "max": 10},
        "conditions": conditions_list if conditions_list is not None else [],
    }


async def _cast_ooc(spell: Spell, *, caster: dict, target_id: str | None = None, rows: dict | None = None):
    """Drive _cast_spell_impl out of combat (make_context -> no combat_state -> in_combat False).
    Returns (packet, conditions_mutations mock, get_player mock) for producer assertions."""
    ctx = make_context(player_id=caster["player_id"])
    mock_db, _conn = make_db_mod()
    table = {caster["player_id"]: caster, **(rows or {})}

    async def _get_player(pid, *, conn=None, for_update=False):
        return table.get(pid)

    queries = MagicMock(get_player=AsyncMock(side_effect=_get_player))
    persistence = MagicMock(update_player_resources=AsyncMock())
    res_mut = MagicMock(update_player_resonance=AsyncMock())
    events = MagicMock(publish_resonance_changed=AsyncMock())
    spells_mod = MagicMock(get_spell=MagicMock(return_value=spell))
    cond_mut = MagicMock(save_player_conditions=AsyncMock())
    raw = await spell_casting._cast_spell_impl(
        ctx,
        spell.id,
        target_id=target_id,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        resonance_mutations_mod=res_mut,
        resonance_events_mod=events,
        spells_mod=spells_mod,
        conditions_mod=conditions,
        conditions_mutations_mod=cond_mut,
    )
    return json.loads(raw), cond_mut, queries.get_player


@pytest.mark.asyncio
async def test_ooc_cast_on_ally_persists_blessed_to_target():
    # AC1: cast Bless on an ally -> Blessed persisted to the TARGET's conditions SSOT; packet signals it.
    ally = _caster("ally_2", conditions_list=[])
    packet, cond_mut, _gp = await _cast_ooc(_bless_spell(), caster=_caster(), target_id="ally_2", rows={"ally_2": ally})

    assert packet["condition_applied"] == "blessed"
    cond_mut.save_player_conditions.assert_awaited_once()
    args, _kwargs = cond_mut.save_player_conditions.call_args
    assert args[0] == "ally_2"  # persisted to the target, not the caster
    assert "blessed" in [c["type"] for c in args[1]]


@pytest.mark.asyncio
async def test_ooc_self_cast_applies_to_caster():
    # AC2: a self-cast (no target_id) applies Blessed to the caster, reusing the for_update caster row.
    packet, cond_mut, get_player = await _cast_ooc(_bless_spell(), caster=_caster("caster_1"))

    assert packet["condition_applied"] == "blessed"
    cond_mut.save_player_conditions.assert_awaited_once()
    args, _kwargs = cond_mut.save_player_conditions.call_args
    assert args[0] == "caster_1"
    assert "blessed" in [c["type"] for c in args[1]]
    assert get_player.await_count == 1  # self-cast reuses the caster row — no extra target fetch


@pytest.mark.asyncio
async def test_ooc_cast_no_applies_condition_does_not_persist():
    # AC3: a spell with no applies_condition produces nothing — existing casts unchanged.
    packet, cond_mut, _gp = await _cast_ooc(_bless_spell(applies_condition=None), caster=_caster())

    assert "condition_applied" not in packet
    cond_mut.save_player_conditions.assert_not_awaited()
