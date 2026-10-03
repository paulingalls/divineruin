"""Authored prose retained for the DM; structured actions alone drive mechanics."""

from copy import deepcopy


def deferred_effects(row):
    effects = []
    for group in ("attacks", "actives", "passives", "reactions"):
        for source in row[group]:
            text = source.get("special") if group == "attacks" else source.get("description")
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
        source = deepcopy(row.get(group))
        if group == "hollow" and row["category"] == "hollow" and row["hollow"]["class"] != "named":
            source.pop("corruption_aura")
            source.pop("resonance_on_death")
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
