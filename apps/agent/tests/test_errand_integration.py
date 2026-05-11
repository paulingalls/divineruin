"""Integration tests for companion errand resolution: companion templates and outcome tiers."""

import random

VALID_ERRAND_TYPES = {"scout", "social", "acquire", "relationship"}
COMPANION_BLOCKED_ERRAND_TYPES: dict[str, frozenset[str]] = {
    "companion_sable": frozenset({"social", "relationship"}),
}


class TestCompanionContext:
    """Validate all companions have required keys for narration templates."""

    REQUIRED_KEYS = {"name", "personality", "speech_style", "voice_id", "errand_frames"}

    def test_all_four_companions_in_context(self) -> None:
        from activity_templates import COMPANION_CONTEXT

        assert set(COMPANION_CONTEXT.keys()) == {
            "companion_kael",
            "companion_lira",
            "companion_tam",
            "companion_sable",
        }

    def test_each_companion_has_required_keys(self) -> None:
        from activity_templates import COMPANION_CONTEXT

        for cid, ctx in COMPANION_CONTEXT.items():
            for key in self.REQUIRED_KEYS:
                assert key in ctx, f"{cid} missing '{key}'"

    def test_errand_frames_cover_allowed_types(self) -> None:
        from activity_templates import COMPANION_CONTEXT

        for cid, ctx in COMPANION_CONTEXT.items():
            blocked = COMPANION_BLOCKED_ERRAND_TYPES.get(cid, frozenset())
            allowed = VALID_ERRAND_TYPES - blocked
            frames = ctx["errand_frames"]
            for etype in allowed:
                assert etype in frames, f"{cid} missing errand_frame for '{etype}'"


class TestOutcomeTiers:
    """resolve_companion_errand produces all 4 tiers across seeded runs."""

    def test_all_four_outcome_tiers_reachable(self) -> None:
        from async_rules import resolve_companion_errand

        companion_data = {"relationship_tier": 2, "attributes": {"wisdom": 14}}
        params = {"errand_type": "scout", "destination": "Ashmark Edge", "dc": 12}
        tiers_seen: set[str] = set()

        for seed in range(500):
            outcome = resolve_companion_errand(companion_data, params, rng=random.Random(seed))
            tiers_seen.add(outcome.tier)
            if len(tiers_seen) == 4:
                break

        assert tiers_seen == {"great_success", "success", "partial", "complication"}
