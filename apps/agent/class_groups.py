"""Attunement class-token resolver (story-010 AC#5).

Items in the catalog can require attunement by a class GROUP ("caster") or by a
concrete class ("artificer") — item.ts ItemAttunement {kind:"class", class:<token>}.
The `class` token therefore holds EITHER a group token or a concrete class id. This
pure function resolves either form to the concrete player class ids it covers, so a
future enforcement caller can match it against a player's class.

ENFORCEMENT IS DEFERRED (decision, ties to debt d30d41fdb474): there is no
equip/use caller checking attunement against player.class in M5.4, so building the
check now would be speculative. This module provides only the resolution primitive.

The class->category map is sourced from the single creation_classes.CLASSES SSOT —
no second copy of the roster lives here, so adding/retiring a class can't drift the
group membership.
"""

from __future__ import annotations

from creation_classes import CLASSES

# Class-group token -> the creation_classes categories it spans. "caster" is every
# spellcasting tradition (arcane + primal + divine); martial/shadow/support are not
# casters. Add a token here only when an item's attunement actually uses it.
_GROUP_CATEGORIES: dict[str, frozenset[str]] = {
    "caster": frozenset({"arcane", "primal", "divine"}),
}


def resolve_attunement_classes(token: str) -> frozenset[str]:
    """Return the concrete class ids that satisfy an attunement `class` token.

    The token is EITHER a class-group token ("caster" -> every spellcasting class)
    OR a concrete class id ("artificer" -> just that class). Raises ValueError on a
    token that is neither, so an item authored with a bad attunement token fails
    loud rather than silently matching no class.
    """
    categories = _GROUP_CATEGORIES.get(token)
    if categories is not None:
        return frozenset(cid for cid, c in CLASSES.items() if c.category in categories)
    if token in CLASSES:
        return frozenset({token})
    known = ", ".join(sorted(_GROUP_CATEGORIES))
    raise ValueError(f"unknown attunement class token {token!r}; known groups: {known}; or a concrete class id")
