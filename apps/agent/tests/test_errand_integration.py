"""Integration tests for companion errand resolution: companion templates and outcome tiers."""

import json
import random
from pathlib import Path

# Read the block rule from the content the dispatch gates actually enforce
# (errand_tools/_dispatch_companion_errand_impl and the server's validateErrandDispatch both
# read `blocked_companions`). A hardcoded copy here cannot red when content unblocks a pair:
# the gate would let it through and activity_templates renders an empty `Errand frame:`.
_TEMPLATES = json.loads((Path(__file__).resolve().parents[3] / "content" / "errand_templates.json").read_text())
VALID_ERRAND_TYPES = {t["id"] for t in _TEMPLATES}
COMPANION_BLOCKED_ERRAND_TYPES: dict[str, frozenset[str]] = {}
for _t in _TEMPLATES:
    for _cid in _t["blocked_companions"]:
        COMPANION_BLOCKED_ERRAND_TYPES[_cid] = COMPANION_BLOCKED_ERRAND_TYPES.get(_cid, frozenset()) | frozenset(
            {_t["id"]}
        )


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
        from errand_resolution import companion_errand_data

        # A real derived companion payload, not a hand-rolled dict: the resolver reads
        # id/name off it and the production caller builds it here.
        companion_data = {**companion_errand_data({"class": "warrior"}), "relationship_tier": 2}
        params = {"errand_type": "scout", "destination": "Ashmark Edge", "dc": 12}
        tiers_seen: set[str] = set()

        for seed in range(500):
            outcome = resolve_companion_errand(companion_data, params, rng=random.Random(seed))
            tiers_seen.add(outcome.tier)
            if len(tiers_seen) == 4:
                break

        assert tiers_seen == {"great_success", "success", "partial", "complication"}
