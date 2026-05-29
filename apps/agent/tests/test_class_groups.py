"""Tests for the attunement class-token resolver (story-010 AC#5).

Pure deterministic function — no DB. Resolves an item attunement `class` token to
the concrete player class ids it covers. The token is EITHER a class-GROUP token
(the catalog's "requires attunement by a caster") OR a concrete class id (the
artificers_portable_lab's "artificer"), sourcing the class->category map from the
single creation_classes.CLASSES SSOT (no duplicated table). Enforcement (checking a
player's class against an item's attunement at equip/use) is DEFERRED — there is no
equip/use caller in M5.4; this only provides the resolution primitive.
"""

import pytest

import class_groups as cg
import creation_classes as cc


def _classes_in(*categories: str) -> frozenset[str]:
    return frozenset(cid for cid, c in cc.CLASSES.items() if c.category in categories)


class TestResolveAttunementClasses:
    def test_caster_resolves_to_arcane_primal_divine_classes(self):
        # "caster" = every spellcasting class: arcane + primal + divine (9 of 18).
        resolved = cg.resolve_attunement_classes("caster")
        assert resolved == _classes_in("arcane", "primal", "divine")
        assert len(resolved) == 9

    def test_caster_includes_known_casters(self):
        resolved = cg.resolve_attunement_classes("caster")
        for cid in ("mage", "cleric", "druid", "paladin", "oracle", "artificer"):
            assert cid in resolved

    def test_caster_excludes_martial_shadow_support(self):
        resolved = cg.resolve_attunement_classes("caster")
        for cid in ("warrior", "guardian", "skirmisher", "rogue", "spy", "whisper", "bard", "diplomat", "marshal"):
            assert cid not in resolved

    def test_concrete_class_token_resolves_to_itself(self):
        # artificers_portable_lab uses class:"artificer" — a concrete class id, not
        # a group. It must resolve to exactly that single class, not raise.
        assert cg.resolve_attunement_classes("artificer") == frozenset({"artificer"})

    def test_returns_frozenset(self):
        assert isinstance(cg.resolve_attunement_classes("caster"), frozenset)
        assert isinstance(cg.resolve_attunement_classes("artificer"), frozenset)

    def test_unknown_token_fails_loud(self):
        # An item authored with a token that is neither a group nor a real class id
        # must fail loud, not silently resolve to an empty (matches-nobody) set.
        with pytest.raises(ValueError):
            cg.resolve_attunement_classes("wizard")

    def test_resolved_ids_are_real_classes(self):
        # Every resolved id must be a real CLASSES key (no dangling group member).
        assert cg.resolve_attunement_classes("caster") <= frozenset(cc.CLASSES)
