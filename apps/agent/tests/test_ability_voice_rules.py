"""Every authored base and mentor form has an explicit delivery policy."""

import json
from pathlib import Path

import pytest

import abilities
import ability_voice_rules as voice
import mentor_variants
from combat_ability_gate import declared_ability

CONTENT = Path(__file__).resolve().parents[3] / "content"


def assert_catalog(rows, policies):
    assert len(rows) == 145
    ids = {abilities.parse_ability_row(row["id"], row).id for row in rows}
    assert len(ids) == len(rows)
    approved = json.loads((Path(__file__).parent / "fixtures/approved_ability_delivery.json").read_text())
    assert set(approved) == ids
    assert dict(policies) == approved
    assert set(policies) == ids
    classes = [voice.BOTH, voice.NEITHER, voice.SOURCE, voice.PREPARATION, voice.HEARING, set(voice.SPELLS)]
    assert sum(map(len, classes)) == len(ids)
    assert set().union(*classes) == ids
    for row in rows:
        assert voice.policy(row["id"]) in voice.DeliveryPolicy
        if row.get("spell_id"):
            assert voice.SPELLS[row["id"]] == row["spell_id"]


def test_complete_catalog_and_variant_floor_uses_actual_loaders():
    rows = json.loads((CONTENT / "archetype_abilities.json").read_text())
    assert_catalog(rows, voice.POLICIES)
    variants = json.loads((CONTENT / "mentor_variants.json").read_text())
    assert len(variants) == 88
    bases = set()
    for row in variants:
        variant = mentor_variants.parse_mentor_variant_row(row["id"], row)
        bases.add(variant.ability_id)
        assert voice.policy(variant.ability_id)
        resolved = declared_ability(variant.id)
        assert resolved is not None and resolved[0].id == variant.ability_id
    assert len(bases) == 44


def test_unknown_base_and_variant_do_not_default_to_nonspoken(monkeypatch):
    with pytest.raises(ValueError, match="Unclassified"):
        voice.require_ability_delivery("invented", None, "speaker", [])
    variant = next(iter(mentor_variants.get_variants_for_ability("guardian_fortify")))
    monkeypatch.delitem(voice.POLICIES, variant.ability_id)
    with pytest.raises(ValueError, match="Unclassified"):
        resolved = declared_ability(variant.id)
        assert resolved is not None
        voice.require_ability_delivery(resolved[0].id, None, "speaker", [])
