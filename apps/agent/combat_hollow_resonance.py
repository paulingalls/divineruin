"""Transaction-local caster totals shared by casts, deaths, pause and wrap."""

import combat_spatial
from hollow_resonance import apply_corruption_aura


def cast_generation(state, caster, spell, generated):
    auras = []
    origin = None
    if state is not None:
        sources = [
            p
            for p in state.participants
            if p.type == "enemy" and p.hollow is not None and not p.is_dead and not p.is_fallen and p.hp_current > 0
        ]
        if sources:
            spatial = combat_spatial.require_spatial(state)
            origin = combat_spatial.position(spatial, caster.player_id)
            auras = [(combat_spatial.position(spatial, p.id), p.hollow["corruption_aura"]) for p in sources]
    return apply_corruption_aura(generated, spell.focus_cost, caster.corruption_level, origin, auras)


def current_total(state, caster):
    return getattr(state, "_resonance_totals", {}).get(caster.player_id, caster.resonance.current)


def stage_total(state, player_id, total):
    if state is not None:
        if not hasattr(state, "_resonance_totals"):
            state._resonance_totals = {}
        state._resonance_totals[player_id] = total


def take_totals(state):
    totals = getattr(state, "_resonance_totals", {})
    if hasattr(state, "_resonance_totals"):
        delattr(state, "_resonance_totals")
    return totals
