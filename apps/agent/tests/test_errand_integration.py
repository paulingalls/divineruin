"""Integration tests for companion errands: companion templates, narration context, E2E dispatch."""

import random
from datetime import UTC, datetime

from errand_rules import COMPANION_ERRAND_CONFIG, VALID_ERRAND_TYPES, compute_errand_dispatch


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
            bonus = COMPANION_ERRAND_CONFIG.get(cid)
            blocked = bonus.blocked_errand_types if bonus else frozenset()
            allowed = VALID_ERRAND_TYPES - blocked
            frames = ctx["errand_frames"]
            for etype in allowed:
                assert etype in frames, f"{cid} missing errand_frame for '{etype}'"


class TestScoutDangerousOutcomeDistribution:
    """E2E: Dispatch scout errand to Dangerous zone, verify outcome distribution."""

    def test_outcome_distribution(self) -> None:
        """Run 1000 seeded dispatches; verify injury ~25%, emergency ~5%, all tiers reachable."""
        injury_count = 0
        emergency_count = 0
        n = 1000
        start = datetime(2026, 1, 1, tzinfo=UTC)

        for seed in range(n):
            result = compute_errand_dispatch("scout", "dangerous", "companion_tam", start, rng=random.Random(seed))
            if result.risk_outcome == "injured":
                injury_count += 1
            elif result.risk_outcome == "emergency":
                emergency_count += 1

            assert 4 * 3600 <= result.duration_seconds <= 8 * 3600

        assert 150 <= injury_count <= 350, f"injury: {injury_count}"
        assert 10 <= emergency_count <= 100, f"emergency: {emergency_count}"

    def test_all_four_outcome_tiers_reachable(self) -> None:
        """resolve_companion_errand produces all 4 tiers over many seeds."""
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


class TestNarrationContext:
    """Verify risk_outcome flows into narration context."""

    def test_dispatch_result_contains_risk_outcome(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        has_injury = False
        for seed in range(200):
            result = compute_errand_dispatch("scout", "dangerous", "companion_tam", start, rng=random.Random(seed))
            if result.risk_outcome != "none":
                has_injury = True
                break
        assert has_injury, "No non-none risk in 200 seeds"

    def test_companion_tags_populated_for_kael_scout(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        result = compute_errand_dispatch("scout", "safe", "companion_kael", start, rng=random.Random(0))
        assert "reduced_injury_risk" in result.companion_tags


class TestSlotEnforcement:
    """Verify slot enforcement blocks second errand."""

    def test_companion_slot_rejects_when_active(self) -> None:
        from errand_rules import validate_errand_dispatch

        result = validate_errand_dispatch("scout", "safe", "companion_kael", companion_slot_active=True)
        assert not result.valid
        assert any("slot" in e.lower() for e in result.errors)

    def test_artificer_dual_crafting(self) -> None:
        from errand_rules import validate_slot_limits

        result = validate_slot_limits(
            slot_counts={"training": 0, "crafting": 1, "companion": 0},
            activity_slot="crafting",
            archetype="artificer",
            has_portable_lab=True,
        )
        assert result.valid

        result_full = validate_slot_limits(
            slot_counts={"training": 1, "crafting": 1, "companion": 0},
            activity_slot="crafting",
            archetype="artificer",
            has_portable_lab=True,
        )
        assert not result_full.valid
