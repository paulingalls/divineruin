"""Choir inventory dispositions name delivered subeffects and deferred guidance."""

import importlib

CHOIR = {
    ("attacks", "Memory Scream"): (
        "executable",
        ("60 ft", "WIS DC18", "3d8 psychic", "Stunned duration1", "success no damage"),
        ("choir_actions.resolve_area", "combat_enemy_action.resolve_save_damage_action"),
        "none",
    ),
    ("attacks", "Dissonant Chord"): (
        "executable",
        ("120 ft", "hit then CON DC18", "2d10+6 psychic", "Deafened duration10"),
        ("choir_actions.require_targets", "combat_enemy_action.resolve_combined_attack_action"),
        "none",
    ),
    ("passives", "No Physical Form"): (
        "executable",
        ("psychic/radiant/thunder/force only", "grapple/restraint immunity", "touch spells refused"),
        ("choir_encounter.damage", "choir_encounter.guard_declaration"),
        "none",
    ),
    ("passives", "Aura of Lost Voices"): (
        "executable",
        ("600 ft", "turn start WIS DC15", "concentration loss", "outside-combat skill disadvantage"),
        ("choir_encounter.turn_start", "choir_scene.check_data"),
        "none",
    ),
    ("passives", "Memory Predator"): (
        "narrative",
        ("strong emotion", "priority targets"),
        (),
        "No automatic emotional target selection",
    ),
    ("passives", "Resonance Core"): (
        "executable",
        ("DC18 Perception/Arcana", "Search/Exposed/Destroyed", "owner-scoped persistence"),
        ("choir_encounter.search", "choir_scene.end"),
        "none",
    ),
    ("actives", "Stolen Melody"): (
        "mixed",
        ("recharge5-6", "WIS DC20", "Charmed duration1d4", "approach source once per round", "stolen voice"),
        ("choir_actions.resolve_effect", "choir_effects.approach"),
        "The DM speaks in the stolen voice; no automatic voice imitation",
    ),
    ("actives", "Cacophony"): (
        "executable",
        (
            "encounter uses1",
            "60 ft",
            "CON DC18",
            "4d8 thunder",
            "success half damage",
            "Deafened both outcomes",
            "Stunned failure only duration1",
        ),
        ("choir_actions.resolve_area", "combat_enemy_action.resolve_save_damage_action"),
        "none",
    ),
    ("actives", "Silence Void"): (
        "executable",
        ("encounter uses1", "30 ft", "3 rounds", "verbal refusal before costs", "legal player input remains usable"),
        ("choir_effects.inflict_silence", "choir_effects.advance_round"),
        "none",
    ),
    ("reactions", "Harmonic Shield"): (
        "executable",
        ("verbal spell", "caster WIS DC16", "redirect to caster", "single real cast"),
        ("choir_reaction.effective_declaration",),
        "none",
    ),
    ("hollow", "hollow"): (
        "mixed",
        (
            "600 ft casting aura",
            "death Resonance5",
            "radiant/psychic double damage",
            "silence suppression2 rounds",
            "class/veil guidance",
        ),
        (
            "combat_hollow_resonance.cast_generation",
            "hollow_resonance.resolve_resonance_on_death",
            "choir_encounter.damage",
            "choir_effects.exposure",
        ),
        "Class and veil_effect are narrative guidance; raw corruption generation and microphone disabling are rejected",
    ),
}


def assert_choir_disposition(key, entry):
    status, effects, bindings, deferred = CHOIR[key[1:]]
    assert entry["status"] == status, key
    assert entry["deferred"] == deferred, key
    assert entry["duplicate"] == "none", key
    assert entry["effects"] == "; ".join(effects), key
    assert entry["resolver"] == (" / ".join(bindings) or "DM narration only"), key
    for binding in bindings:
        module, name = binding.rsplit(".", 1)
        assert callable(getattr(importlib.import_module(module), name)), binding
