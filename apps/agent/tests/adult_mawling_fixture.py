"""Private adult encounter for tests of adult-only Mawling mechanics."""

import json
from copy import deepcopy

from sample_fixtures import CONTENT_ROOT, TEST_CREATURES

from creature_combat import translate_creature


def adult_template(encounter_id="adult_mawling_pair", role="standard"):
    templates = json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
    template = deepcopy(next(t for t in templates if t["id"] == "ruins_mawling_pair"))
    template.update(id=encounter_id, recommended_party_level=5)
    for index, enemy in enumerate(template["enemies"]):
        enemy.update(creature_id="hollow_mawling", role=role if index == 0 else "standard")
    for zone in template["scene_placement"]["zones"].values():
        zone["radius_ft"] = 10
    return template


def adult_encounter():
    template = adult_template()
    template["enemies"] = [
        translate_creature(
            TEST_CREATURES[ref["creature_id"]], encounter_id=template["id"], enemy_id=ref["id"], role=ref["role"]
        )
        for ref in template["enemies"]
    ]
    return template
