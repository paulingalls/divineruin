"""Silent absorption failures exercised through the real cast and phase commit."""

from dataclasses import replace

from combat.test_spell_damage_lands import load_combat
from combat.test_spell_damage_lands import spell_fight as spell_fight
from combat.test_veilrender_absorb import ally_cast, prepare_absorb
from voice_condition_fixtures import participant

import choir_reaction
import combat_resolve_phase


async def test_fallen_veilrender_is_not_healed(spell_fight, monkeypatch):
    ctx = spell_fight
    await prepare_absorb(ctx)
    validate = combat_resolve_phase._prevalidate_ability_focus

    async def defeat_after_validation(session, state, *args, **kwargs):
        result = await validate(session, state, *args, **kwargs)
        boss = participant(state, "foe")
        boss.hp_current = 0
        boss.is_fallen = True
        return result

    monkeypatch.setattr(combat_resolve_phase, "_prevalidate_ability_focus", defeat_after_validation)
    cast = await ally_cast(ctx)
    state = await load_combat(ctx.userdata.combat_state.combat_id)
    assert participant(state, "foe").hp_current == 0
    assert participant(state, "foe").is_fallen
    assert "absorbed" not in cast
    assert cast["damage_results"] == [] and "No effective recipients" in cast["recipient_status"]


async def test_duplicate_recipients_heal_once_per_cast(spell_fight, monkeypatch):
    ctx = spell_fight
    await prepare_absorb(ctx, "divine_bless", targets=["foe", "foe"])
    redirect = choir_reaction.effective_declaration

    async def duplicate_effective_recipients(session, state, caster, declaration, *, progress=None):
        effective = await redirect(session, state, caster, declaration, progress=progress)
        assert effective is not None
        return replace(effective, target_ids=["foe", "foe"])

    monkeypatch.setattr(choir_reaction, "effective_declaration", duplicate_effective_recipients)
    cast = await ally_cast(ctx)
    state = await load_combat(ctx.userdata.combat_state.combat_id)
    assert participant(state, "foe").hp_current == 76
    assert cast["absorbed"] == [{"effect": "Absorb Magic", "target_id": "foe", "healed": 6, "hp_current": 76}]
