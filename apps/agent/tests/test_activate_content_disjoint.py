"""Content guard for activate_tools._resolve_kind's ordered namespaces.

An id present in two namespaces silently routes to whichever is checked first and leaves the other
capability unreachable. This pin keeps every routed namespace pairwise disjoint.
"""

import json
from itertools import combinations
from pathlib import Path

from activate_tools import _RESERVED
from veil_ward import VEIL_ANCHORS

_CONTENT = Path(__file__).resolve().parents[3] / "content"


def _ids(filename: str) -> set[str]:
    rows = json.loads((_CONTENT / filename).read_text())
    return {row["id"] for row in rows}


def test_activate_routed_namespaces_are_pairwise_disjoint():
    namespaces = {
        "reserved": set(_RESERVED),
        "anchors": set(VEIL_ANCHORS),
        "spells": _ids("spells.json"),
        "abilities": _ids("archetype_abilities.json"),
        "variants": _ids("mentor_variants.json"),
    }
    for (left_name, left_ids), (right_name, right_ids) in combinations(namespaces.items(), 2):
        collisions = left_ids & right_ids
        assert not collisions, (
            f"activate() namespace collision between {left_name} and {right_name}; "
            f"the earlier route shadows the later one: {sorted(collisions)}"
        )
