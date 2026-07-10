"""Content guard for activate_tools._resolve_kind's spell-before-ability routing.

``activate`` classifies an id by trying ``get_spell`` first, then ``get_ability`` (activate_tools.py
``_resolve_kind``). That order is only unambiguous while spell ids and ability ids are disjoint: a
content id present in BOTH would silently route to the spell path, leaving the same-id ability
unreachable via ``activate`` with no error. The dispatcher docstring asserts disjointness was verified
by hand this story; this test pins it so a future colliding content id fails loud instead.
"""

import json
from pathlib import Path

from activate_tools import _RESERVED
from veil_ward import VEIL_ANCHORS

_CONTENT = Path(__file__).resolve().parents[3] / "content"


def _ids(filename: str) -> set[str]:
    rows = json.loads((_CONTENT / filename).read_text())
    return {row["id"] for row in rows}


def test_spell_and_ability_ids_are_disjoint():
    spell_ids = _ids("spells.json")
    ability_ids = _ids("archetype_abilities.json")
    collisions = spell_ids & ability_ids
    assert not collisions, (
        f"spell/ability id collision breaks activate() routing (spell wins, ability unreachable): {sorted(collisions)}"
    )


def test_reserved_and_anchor_ids_are_disjoint_from_content_ids():
    # _resolve_kind checks reserved tokens and Veil-Anchor ids BEFORE spells/abilities, so a
    # content id colliding with either is silently shadowed — the reserved/anchor kind wins and the
    # real spell/ability is permanently unreachable via activate(), with no error. Pin it here so a
    # future colliding content id fails loud instead of routing to the wrong _impl.
    content_ids = _ids("spells.json") | _ids("archetype_abilities.json")

    reserved_collisions = _RESERVED & content_ids
    assert not reserved_collisions, (
        f"reserved token collides with a spell/ability id; the reserved kind shadows the content, "
        f"leaving it uncastable via activate(): {sorted(reserved_collisions)}"
    )

    anchor_collisions = set(VEIL_ANCHORS) & content_ids
    assert not anchor_collisions, (
        f"Veil-Anchor id collides with a spell/ability id; the anchor kind shadows the content, "
        f"leaving it uncastable via activate(): {sorted(anchor_collisions)}"
    )
