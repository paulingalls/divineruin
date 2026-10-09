"""Authored prose retained for the DM; structured actions alone drive mechanics."""

from copy import deepcopy


def deferred_effects(row, *, composite=False):
    effects = []
    for group in ("attacks", "actives", "passives", "reactions"):
        for source in row[group]:
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
            if row["id"] == "hollow_choir":
                source.pop("vulnerable_to")
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
