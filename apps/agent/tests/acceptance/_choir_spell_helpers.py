"""Shared real-cast driver for Choir spell compatibility checks."""

import json
from unittest.mock import patch

from acceptance._capstone_helpers import _d20, _resolve_round

import combat_turn
import db_mutations


async def give_guest_threshold_mercy(pool, guest_id):
    await pool.execute(
        "UPDATE players SET data = data || $2::jsonb WHERE player_id = $1",
        guest_id,
        json.dumps({"divine_favor": {"patron": "mortaen", "level": 0, "max": 100}}),
    )


async def assert_guest_spell_exception(ctx, resolved, guest_id):
    from query_tools import _query_info_impl

    facts = json.loads(await _query_info_impl(ctx, "combat"))["choir"]
    assert "divine_sacred_flame" in facts["engine_damage_spell_ids"]
    assert facts["engine_damage_spell_exceptions"] == {guest_id: ["divine_sacred_flame"]}
    assert resolved["choir"]["engine_damage_spell_exceptions"] == facts["engine_damage_spell_exceptions"]


async def bolt(ctx, face=20):
    state = ctx.userdata.combat_state
    declarations = {p.id: {"type": "defend"} for p in state.participants if not p.is_fallen}
    declarations[ctx.userdata.player_id] = {"type": "ability", "action": "arcane_bolt", "target_id": "choir_zone"}
    await combat_turn._declare_phase_impl(ctx, declarations)
    with patch("check_resolution.dice_roll", return_value=_d20(face)):
        return await _resolve_round(ctx)


async def assert_core_defenses(ctx, facts, query_info):
    assert facts["engine_damage_spell_ids"] == [
        "arcane_bolt",
        "arcane_magic_missile",
        "arcane_disintegrate",
        "divine_sacred_flame",
        "divine_sacred_word",
        "divine_flame_strike",
        "divine_divine_judgment",
    ]
    assert set(facts["core_defenses"]["allowed_damage"]) == {"force", "psychic", "radiant", "thunder"}
    assert facts["core_defenses"]["vulnerable_to"] == ["psychic", "radiant"]
    source = ctx.userdata.combat_state.get_participant("choir_zone")
    source.damage_affinities["immune"].append("force")
    source.damage_affinities["vulnerable"] = ["thunder"]
    await db_mutations.save_combat_state(ctx.userdata.combat_state.combat_id, ctx.userdata.combat_state.to_dict())
    changed = json.loads(await query_info(ctx, "combat"))["choir"]
    assert set(changed["core_defenses"]["allowed_damage"]) == {"psychic", "radiant", "thunder"}
    assert changed["core_defenses"]["vulnerable_to"] == ["thunder"]
    assert "arcane_bolt" not in changed["engine_damage_spell_ids"]
