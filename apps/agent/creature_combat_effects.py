"""Retain DM guidance for effects without structured combat consumers."""

from copy import deepcopy

from combat_damage_affinity import DAMAGE_TYPES

_EXECUTED_PASSIVES = {
    ("corrupted_treant", "Vulnerability to Fire"): None,
    ("corrupted_treant", "Resistance"): None,
    ("dire_bear", "Thick Hide"): None,
    ("war_golem", "Damage Immunity"): None,
    ("deepstone_guardian", "Damage Immunity"): None,
    ("hollow_weaver", "Fragile Form"): None,
    ("cave_wyrm", "Scales"): "Climbs 30 ft and burrows 10 ft.",
    ("tidecaller_eel", "Electricity Absorption"): "Heals HP equal to lightning damage dealt to it.",
    ("thunderbird", "Lightning Absorption"): "Heals equal to lightning damage dealt to it.",
}


def deferred_effects(row, *, composite=False):
    effects = []
    for group in ("attacks", "actives", "passives", "reactions"):
        for source in row[group]:
            key = (row["id"], source["name"])
            if group == "passives" and key in _EXECUTED_PASSIVES:
                residual = _EXECUTED_PASSIVES[key]
                if residual is None:
                    continue
                source = {**source, "description": residual}
            text = source.get("special") if group == "attacks" else source.get("description")
            if row["id"] == "hollow_choir" and source["name"] in {
                "No Physical Form",
                "Aura of Lost Voices",
                "Resonance Core",
            }:
                continue
            if row["id"] == "hollow_choir" and (
                "resolution" in source or source.get("kind") in ("silence", "spell_redirect")
            ):
                continue
            if row["id"] == "hollow_choir" and source.get("kind") == "charm":
                source = {"name": source["name"], "description": "The DM speaks in the stolen voice."}
            if "turn_start_damage" in source:
                continue
            if "durability_rider" in source:
                continue
            if not text:
                continue
            effects.append(
                {
                    "group": group,
                    "name": source["name"],
                    "source": deepcopy(source),
                    "reason": "Authored prose is DM guidance; only structured fields execute.",
                }
            )
    for group in ("multiattack", "signature_ability", "hollow"):
        if group == "multiattack" and composite and row.get("multiattack_sequence"):
            continue
        source = deepcopy(row.get(group))
        if (
            group == "hollow"
            and row["category"] == "hollow"
            and (row["hollow"]["class"] != "named" or row["id"] == "hollow_choir")
        ):
            source.pop("corruption_aura")
            source.pop("resonance_on_death")
        if group == "hollow" and source:
            source["vulnerable_to"] = [
                v for v in source["vulnerable_to"] if v not in (*DAMAGE_TYPES, "physical_damage")
            ]
        if source:
            name = source.get("name", group) if isinstance(source, dict) else source
            effects.append(
                {
                    "group": group,
                    "name": name,
                    "source": deepcopy(source),
                    "reason": "Narrative guidance; no automatic combat consumer.",
                }
            )
    return effects
