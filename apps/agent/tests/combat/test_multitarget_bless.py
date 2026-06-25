"""M4.8 story-007: multi-target Bless — OOC cast path + max_targets cap.

The single-target Bless producer (story-004) lands `blessed` on ONE target. Bless is specced
"up to three allies"; this story extends the OUT-OF-COMBAT cast (`_resolve_cast`, gated on not
session.in_combat) to apply + persist `blessed` to EACH named ally's players.data, capped by the
spell's `max_targets` (reject >cap with a ToolError, before any write). The shared foundation
(`Spell.max_targets`, `spells.validate_target_count`) is reused by the in-combat path (story-012).
The single-target path stays unchanged when `target_ids` is absent.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat.test_bless_producer import _caster  # reuse the OOC caster-dict builder
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

import conditions
import spell_casting
import spells
from spells import Spell


def _bless3(applies_condition: str | None = "blessed") -> Spell:
    """A divine Bless (resonance 0, focus 0) capped at 3 targets — clears the gates with only the
    multi-target producer hook active."""
    return Spell(
        id="divine_bless",
        name="Bless",
        source="divine",
        spell_tier="minor",
        focus_cost=0,
        mechanics="Up to three allies gain +1d4.",
        narration_cue="Warmth settling into bones.",
        audio_cue="",
        resonance_by_source={"divine": 0},
        terrain_effects={},
        concentration=False,
        applies_condition=applies_condition,
        max_targets=3,
    )


async def _cast_ooc_multi(spell, *, caster, target_id=None, target_ids=None, rows=None):
    """Drive _cast_spell_impl out of combat with target_ids. Returns (packet, cond_mut, get_player)."""
    ctx = make_context(player_id=caster["player_id"])
    mock_db, _conn = make_db_mod()
    table = {caster["player_id"]: caster, **(rows or {})}

    async def _get_player(pid, *, conn=None, for_update=False):
        return table.get(pid)

    queries = MagicMock(get_player=AsyncMock(side_effect=_get_player))
    persistence = MagicMock(update_player_resources=AsyncMock())
    res_mut = MagicMock(update_player_resonance=AsyncMock())
    events = MagicMock(publish_resonance_changed=AsyncMock())
    # Wire the REAL cap validator into the mocked catalog so the over-cap path exercises real logic.
    spells_mod = MagicMock(get_spell=MagicMock(return_value=spell), validate_target_count=spells.validate_target_count)
    cond_mut = MagicMock(save_player_conditions=AsyncMock())
    raw = await spell_casting._cast_spell_impl(
        ctx,
        spell.id,
        target_id=target_id,
        target_ids=target_ids,
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
async def test_ooc_three_allies_each_get_blessed():
    # AC1: name three allies -> each ally's players.data gets blessed persisted.
    rows = {f"ally_{i}": _caster(f"ally_{i}", conditions_list=[]) for i in (1, 2, 3)}
    packet, cond_mut, _gp = await _cast_ooc_multi(
        _bless3(), caster=_caster(), target_ids=["ally_1", "ally_2", "ally_3"], rows=rows
    )

    assert packet["condition_applied"] == "blessed"
    assert cond_mut.save_player_conditions.await_count == 3
    persisted_ids = {call.args[0] for call in cond_mut.save_player_conditions.await_args_list}
    assert persisted_ids == {"ally_1", "ally_2", "ally_3"}
    for call in cond_mut.save_player_conditions.await_args_list:
        assert "blessed" in [c["type"] for c in call.args[1]]


@pytest.mark.asyncio
async def test_ooc_over_cap_rejects_before_write():
    # AC2: more than max_targets (3) is rejected with a ToolError and deducts/persists nothing.
    rows = {f"ally_{i}": _caster(f"ally_{i}", conditions_list=[]) for i in (1, 2, 3, 4)}
    with pytest.raises(ToolError, match="at most 3"):
        await _cast_ooc_multi(
            _bless3(), caster=_caster(), target_ids=["ally_1", "ally_2", "ally_3", "ally_4"], rows=rows
        )


@pytest.mark.asyncio
async def test_ooc_single_target_path_unchanged():
    # AC3: a single-target cast (target_id, no target_ids) still persists to exactly the one target.
    ally = _caster("ally_2", conditions_list=[])
    packet, cond_mut, _gp = await _cast_ooc_multi(
        _bless3(), caster=_caster(), target_id="ally_2", rows={"ally_2": ally}
    )

    assert packet["condition_applied"] == "blessed"
    cond_mut.save_player_conditions.assert_awaited_once()
    assert cond_mut.save_player_conditions.await_args.args[0] == "ally_2"


@pytest.mark.asyncio
async def test_ooc_mix_nonplayer_narrates_player_persists():
    # AC4: a non-player ally (absent from the table) narrates without a write; player allies persist.
    rows = {"ally_1": _caster("ally_1", conditions_list=[])}  # "kael" intentionally absent (non-player)
    packet, cond_mut, _gp = await _cast_ooc_multi(_bless3(), caster=_caster(), target_ids=["ally_1", "kael"], rows=rows)

    assert packet["condition_applied"] == "blessed"  # landed on >=1 target
    cond_mut.save_player_conditions.assert_awaited_once()  # only the player ally persisted
    assert cond_mut.save_player_conditions.await_args.args[0] == "ally_1"
