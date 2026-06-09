"""Tests for settlement_generation — the pure NPC-population rules engine (M6.2 / story-003).

generate_settlement_npcs(tier, personality) turns a settlement into concrete role counts;
instantiate_npc_from_template(role, tier, personality, overrides) layers tier+personality
modifiers onto M6.1's create_npc_from_archetype output. Both are pure (no LLM, no DB). The
fixture seeds the real content/*.json catalogs (settlement_templates + role_archetypes) via
the set_* seams so tests exercise the shipped data, not hand-rolled stubs.
"""

import json
import random
from pathlib import Path

import pytest

from role_archetypes import parse_role_archetype_row, set_role_archetypes
from settlement_generation import _effective_ranges, generate_settlement_npcs
from settlement_templates import parse_settlement_template_row, set_settlement_templates

_CONTENT = Path(__file__).resolve().parents[3] / "content"
_TEMPLATES = json.loads((_CONTENT / "settlement_templates.json").read_text())
_ARCHETYPES = json.loads((_CONTENT / "role_archetypes.json").read_text())


@pytest.fixture(autouse=True)
def _seed_catalogs():
    """Seed both content catalogs from the real JSON before each test."""
    tiers: dict[str, dict] = {}
    personalities: dict[str, dict] = {}
    for e in _TEMPLATES:
        row = parse_settlement_template_row(e["id"], e)
        (tiers if e["kind"] == "tier" else personalities)[e["id"]] = row
    set_settlement_templates(tiers, personalities)
    set_role_archetypes({e["id"]: parse_role_archetype_row(e["id"], e) for e in _ARCHETYPES})


class TestGenerate:
    def test_counts_within_effective_ranges_and_roles_valid(self):
        counts = generate_settlement_npcs("village", "military", rng=random.Random(0))
        ranges = _effective_ranges("village", "military")
        assert set(counts) == set(ranges)
        for role_id, n in counts.items():
            assert ranges[role_id]["min"] <= n <= ranges[role_id]["max"]

    def test_hamlet_is_austere(self):
        # Hamlet has only innkeeper (0-1) + guard (0-2). No personality should add a
        # big-settlement role like scholar_sage or merchant_jeweler.
        counts = generate_settlement_npcs("hamlet", "scholarly", rng=random.Random(1))
        assert "merchant_jeweler" not in counts
        assert all(n <= 3 for n in counts.values())

    def test_seeded_rng_is_deterministic(self):
        a = generate_settlement_npcs("city", "prosperous", rng=random.Random(7))
        b = generate_settlement_npcs("city", "prosperous", rng=random.Random(7))
        assert a == b

    def test_keldaran_hold_maps_to_city(self):
        # keldaran_hold has no tier row (City-scale per spec); generate normalizes to city.
        assert _effective_ranges("keldaran_hold", "military") == _effective_ranges("city", "military")

    def test_unknown_tier_and_personality_fail_loud(self):
        with pytest.raises(ValueError):
            generate_settlement_npcs("metropolis", "military", rng=random.Random(0))
        with pytest.raises(ValueError):
            generate_settlement_npcs("city", "bogus", rng=random.Random(0))


class TestEffectiveRanges:
    def test_frequency_modifier_raises_present_role(self):
        # military guard +2: town guard 6-12 -> 8-14.
        r = _effective_ranges("town", "military")
        assert r["guard"] == {"min": 8, "max": 14}

    def test_positive_modifier_introduces_absent_role(self):
        # corrupt fence+1 / merchant_black_market+1 in a hamlet (neither present) -> {0,1}.
        r = _effective_ranges("hamlet", "corrupt")
        assert r["fence"] == {"min": 0, "max": 1}
        assert r["merchant_black_market"] == {"min": 0, "max": 1}

    def test_negative_modifier_floors_min_at_zero(self):
        # frontier guard -1: hamlet guard 0-2 -> 0-1 (min floored, not -1).
        r = _effective_ranges("hamlet", "frontier")
        assert r["guard"] == {"min": 0, "max": 1}

    def test_negative_modifier_on_absent_role_is_noop(self):
        # frontier only carries guard-1; it must not introduce any negative-count role.
        r = _effective_ranges("village", "frontier")
        assert all(rng["max"] >= 0 and rng["min"] >= 0 for rng in r.values())
        assert "soldier_ashmark" not in r  # frontier doesn't add it
