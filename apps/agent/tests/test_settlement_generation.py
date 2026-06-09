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

from role_archetypes import (
    DISPOSITIONS,
    create_npc_from_archetype,
    parse_role_archetype_row,
    set_role_archetypes,
)
from settlement_generation import (
    _effective_ranges,
    _shift_disposition,
    generate_settlement_npcs,
    instantiate_npc_from_template,
)
from settlement_templates import (
    get_settlement_personality,
    parse_settlement_template_row,
    set_settlement_templates,
)

_CONTENT = Path(__file__).resolve().parents[3] / "content"
_TEMPLATES = json.loads((_CONTENT / "settlement_templates.json").read_text())
_ARCHETYPES = json.loads((_CONTENT / "role_archetypes.json").read_text())
_ARCHETYPE_IDS = {e["id"] for e in _ARCHETYPES}

# Every SettlementSize (keldaran_hold has no tier row — generate normalizes it to city)
# crossed with every personality. The E2E sweep asserts no unknown role/disposition escapes.
_ALL_TIERS = ["hamlet", "village", "town", "city", "keldaran_hold"]
_ALL_PERSONALITIES = [
    "prosperous",
    "struggling",
    "military",
    "scholarly",
    "corrupt",
    "devout",
    "frontier",
    "refuge",
]


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


class TestShiftDisposition:
    def test_shifts_within_ladder(self):
        assert _shift_disposition("neutral", -1) == "unfriendly"
        assert _shift_disposition("neutral", 1) == "friendly"

    def test_clamps_at_both_ends(self):
        assert _shift_disposition("hostile", -3) == "hostile"
        assert _shift_disposition("trusted", 5) == "trusted"


class TestInstantiate:
    def test_calls_create_npc_and_preserves_base_keys(self):
        npc = instantiate_npc_from_template("innkeeper", "village", "military")
        base = create_npc_from_archetype("innkeeper")
        assert npc["role_archetype"] == base["role_archetype"]
        assert npc["services"] == base["services"]
        assert npc["knowledge_domains"] == base["knowledge_domains"]

    def test_overrides_pass_through(self):
        npc = instantiate_npc_from_template("guard", "town", "military", {"id": "npc_42", "name": "Bran"})
        assert npc["id"] == "npc_42"
        assert npc["name"] == "Bran"

    def test_disposition_modifier_drops_guard_under_corrupt(self):
        # guard default_disposition is neutral; corrupt guard -1 -> unfriendly.
        npc = instantiate_npc_from_template("guard", "city", "corrupt")
        assert npc["default_disposition"] == "unfriendly"

    def test_no_disposition_modifier_leaves_baseline(self):
        base = create_npc_from_archetype("guard")
        npc = instantiate_npc_from_template("guard", "city", "military")  # military has no guard disp mod
        assert npc["default_disposition"] == base["default_disposition"]

    def test_price_modifier_composes_multiplicatively(self):
        base = create_npc_from_archetype("merchant_general_goods")
        prosperous = instantiate_npc_from_template("merchant_general_goods", "city", "prosperous")
        struggling = instantiate_npc_from_template("merchant_general_goods", "city", "struggling")
        assert prosperous["price_modifier"] == pytest.approx(base["price_modifier"] * 1.15)
        assert struggling["price_modifier"] == pytest.approx(base["price_modifier"] * 0.9)

    def test_inventory_richness_set_from_personality(self):
        prosperous = instantiate_npc_from_template("merchant_general_goods", "city", "prosperous")
        struggling = instantiate_npc_from_template("merchant_general_goods", "city", "struggling")
        assert prosperous["inventory_richness"] == 1.2
        assert struggling["inventory_richness"] == 0.8

    def test_keldaran_hold_tier_validates(self):
        # keldaran_hold normalizes to city; a bogus tier fails loud.
        instantiate_npc_from_template("guard", "keldaran_hold", "military")
        with pytest.raises(ValueError):
            instantiate_npc_from_template("guard", "metropolis", "military")


class TestCorruptAcceptance:
    def test_corrupt_raises_blackmarket_frequency_and_drops_guard_disposition(self):
        # story-003 AC: Corrupt raises Fence/Black-Market frequency AND drops Guard disposition.
        ranges = _effective_ranges("city", "corrupt")
        plain = _effective_ranges("city", "military")  # military has no fence/blackmarket freq mod
        assert ranges["fence"]["max"] > plain.get("fence", {"max": 0})["max"]
        assert ranges["merchant_black_market"]["max"] > plain["merchant_black_market"]["max"]
        guard = instantiate_npc_from_template("guard", "city", "corrupt")
        assert DISPOSITIONS.index(guard["default_disposition"]) < DISPOSITIONS.index("neutral")


class TestEndToEnd:
    @pytest.mark.parametrize("tier", _ALL_TIERS)
    @pytest.mark.parametrize("personality", _ALL_PERSONALITIES)
    def test_every_tier_personality_yields_valid_roles_and_dispositions(self, tier, personality):
        # AC4: across all tier x personality combos, generated roles are real archetypes,
        # counts fall within the spec's effective range, and every instantiated NPC has a
        # canonical disposition.
        counts = generate_settlement_npcs(tier, personality, rng=random.Random(123))
        ranges = _effective_ranges(tier, personality)
        assert counts, f"{tier}/{personality} generated an empty population"
        assert set(counts) == set(ranges), f"{tier}/{personality} role set drifted from spec ranges"
        for role_id, n in counts.items():
            assert role_id in _ARCHETYPE_IDS, f"{tier}/{personality} yielded unknown role {role_id!r}"
            lo, hi = ranges[role_id]["min"], ranges[role_id]["max"]
            assert lo <= n <= hi, f"{tier}/{personality} role {role_id!r} count {n} outside [{lo}, {hi}]"
            npc = instantiate_npc_from_template(role_id, tier, personality)
            assert npc["default_disposition"] in DISPOSITIONS
            assert npc["inventory_richness"] == get_settlement_personality(personality)["inventory_modifier"]
            assert isinstance(npc["price_modifier"], (int, float))
