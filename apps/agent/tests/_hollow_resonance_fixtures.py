"""Hollow generation through committed spell and damage consumers."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from _spell_casting_helpers import _known, _player
from sample_fixtures import make_context, make_db_mod
from voice_condition_fixtures import place_actors

from combat_participant import CombatParticipant
from combat_state import CombatState
from creature_combat import translate_creature
from spell_casting import _resolve_cast


def hollow(enemy_id="hollow", creature_id="hollow_mawling"):
    rows = json.loads((Path(__file__).resolve().parents[3] / "content/creatures.json").read_text())
    row = next(r for r in rows if r["id"] == creature_id)
    translated = translate_creature(row, encounter_id="encounter", enemy_id=enemy_id, role="standard")
    p = CombatParticipant(enemy_id, row["name"], "enemy", 10, row["hp"], row["hp"], row["ac"])
    p.creature_id = creature_id
    p.hollow = translated["hollow"]
    return p


def scenario(*, creature_id="hollow_mawling", distance=5):
    ctx = make_context()
    player = CombatParticipant("player_1", "Caster", "player", 20, 20, 20, 14)
    enemy = hollow(creature_id=creature_id)
    state = place_actors(CombatState("combat", [player, enemy], [player.id, enemy.id]))
    assert state.spatial is not None
    state.spatial["positions"][enemy.id]["x"] = distance
    ctx.userdata.combat_state = state
    return ctx, state, enemy


async def cast(ctx, state, spell_id="arcane_magic_missile", *, owner=None, focus=100, ward_mod=None):
    _, conn = make_db_mod()
    persistence = MagicMock(update_player_resources=AsyncMock())
    mutations = MagicMock(update_player_resonance=AsyncMock())
    ward = MagicMock(resolve_scope_ward=AsyncMock(return_value=state.veil_ward))
    result = await _resolve_cast(
        ctx.userdata,
        spell_id,
        conn=conn,
        caster=owner,
        player=_player(focus=focus),
        combat_state=state,
        persistence_mod=persistence,
        resonance_mutations_mod=mutations,
        ward_resolution_mod=ward_mod or ward,
        character_spells_mod=_known(spell_id),
        suppress_resonance_changed=True,
    )
    return result, mutations, persistence
