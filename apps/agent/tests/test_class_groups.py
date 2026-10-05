"""Attunement resolution does not enforce equip/use eligibility."""

import pytest

import class_groups as cg
import creation_classes as cc


def _classes_in(*categories: str) -> frozenset[str]:
    return frozenset(cid for cid, c in cc.CLASSES.items() if c.category in categories)


class TestResolveAttunementClasses:
    def test_caster_resolves_to_arcane_primal_divine_classes(self):
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
        assert cg.resolve_attunement_classes("artificer") == frozenset({"artificer"})

    def test_returns_frozenset(self):
        assert isinstance(cg.resolve_attunement_classes("caster"), frozenset)
        assert isinstance(cg.resolve_attunement_classes("artificer"), frozenset)

    def test_unknown_token_fails_loud(self):
        with pytest.raises(ValueError):
            cg.resolve_attunement_classes("wizard")

    def test_resolved_ids_are_real_classes(self):
        assert cg.resolve_attunement_classes("caster") <= frozenset(cc.CLASSES)
