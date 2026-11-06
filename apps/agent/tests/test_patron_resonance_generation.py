"""Patron generation through activate and the shared transactional casting path."""

import json
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import make_context, make_db_mod

import spell_casting
import spells
from activate_tools import _activate_impl


async def cast(
    patron,
    spell_id="arcane_fireball",
    *,
    spell=None,
    terrain="forest",
    ward=False,
    target_id=None,
    target_ids=None,
    rows=None,
    visit=None,
    corruption=0,
    **facts,
):
    ctx = make_context()
    ctx.userdata.resonance.current = 5
    ctx.userdata.party.primary.corruption_level = corruption
    spell = spell or spells.get_spell(spell_id)
    row = {
        "player_id": "player_1",
        "class": {"arcane": "mage", "divine": "cleric", "primal": "druid"}[spell.source],
        "level": 20,
        "focus": {"current": 50},
        "divine_favor": {"patron": patron},
    }
    table = {"player_1": row, **(rows or {})}
    queries = SimpleNamespace(
        get_player=AsyncMock(side_effect=lambda pid, **kw: table.get(pid)),
        get_players_for_update=AsyncMock(
            side_effect=lambda ids, **kw: {pid: table[pid] for pid in ids if pid in table}
        ),
    )
    database, conn = make_db_mod()
    conn.fetchrow = AsyncMock(return_value=visit)
    persistence = SimpleNamespace(update_player_resources=AsyncMock())
    mutations = SimpleNamespace(update_player_resonance=AsyncMock())
    events = SimpleNamespace(publish_resonance_changed=AsyncMock())
    catalog = spells if spell is spells.get_spell(spell.id) else MagicMock(get_spell=MagicMock(return_value=spell))
    entry = partial(
        spell_casting._cast_spell_impl,
        db_mod=database,
        queries_mod=queries,
        content_mod=SimpleNamespace(get_location_terrain=AsyncMock(return_value=terrain)),
        persistence_mod=persistence,
        resonance_mutations_mod=mutations,
        resonance_events_mod=events,
        spells_mod=catalog,
        concentration_mutations_mod=SimpleNamespace(update_player_concentration=AsyncMock()),
        character_spells_mod=SimpleNamespace(get_known=AsyncMock(return_value=[{"spell_id": spell.id}])),
        ward_resolution_mod=SimpleNamespace(resolve_scope_ward=AsyncMock(return_value={} if ward else None)),
        **facts,
    )
    raw = await _activate_impl(
        ctx,
        spell.id,
        target_id=target_id,
        target_ids=target_ids,
        spells_mod=catalog,
        cast_spell_mod=MagicMock(_cast_spell_impl=entry),
    )
    packet = json.loads(raw)
    generated = packet["resonance_generated"]
    if spell.focus_cost:
        persistence.update_player_resources.assert_awaited_once_with("player_1", focus=50 - spell.focus_cost, conn=conn)
    if generated:
        mutations.update_player_resonance.assert_awaited_once_with("player_1", 4 + generated, conn=conn)
        assert ctx.userdata.resonance.current == 4 + generated
        events.publish_resonance_changed.assert_awaited_once()
    else:
        mutations.update_player_resonance.assert_not_awaited()
        events.publish_resonance_changed.assert_not_awaited()
        assert ctx.userdata.resonance.current == 5
    return packet


@pytest.mark.parametrize(
    "spell_id,expected", [("arcane_fireball", 2), ("arcane_haste", 2), ("arcane_bolt", 0), ("arcane_detect_magic", 1)]
)
async def test_kaelen(spell_id, expected):
    packet = await cast("kaelen", spell_id)
    assert packet["resonance_generated"] == expected
    standard = await cast(None, spell_id)
    if expected != standard["resonance_generated"]:
        assert packet["patron_resonance"] == {
            "patron": "kaelen",
            "applies_to": ["combat_aid"],
            "standard": standard["resonance_generated"],
            "generated": expected,
        }
    else:
        assert "patron_resonance" not in packet
    assert "patron_resonance" not in standard
