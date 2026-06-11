"""Tests for companion relationship DB query, hydration, and errand-affinity persistence
(M6.4 / story-003).

Exercises the REAL companion_relationship_queries functions against a patched DB layer
(db_queries.get_companion_relationship, db_mutations.upsert_companion_relationship for hydration,
and the atomic db_mutations.bump_companion_affinity / cache_companion_tier for the errand nudge),
so no live DB is needed. The pure tier math is covered in tests/test_companion_relationship.py.
"""

import inspect
from unittest.mock import AsyncMock, patch

import pytest

import companion_relationship_queries as crq


@pytest.fixture(autouse=True)
def stub_companion_hydrate_io():
    """Override the global autouse hydrate stub (tests/conftest.py) so the REAL crq functions —
    including hydrate_companion_state — run here against the patched DB layer. Rank/affinity are
    real by default (this module does not opt into stub_companion_errand_affinity_io)."""
    yield


def _patch_db(row):
    """Patch the DB layer: get returns `row`; upsert is an AsyncMock recording its calls."""
    get_p = patch.object(crq, "get_companion_relationship", new_callable=AsyncMock, return_value=row)
    upsert = AsyncMock()
    up_p = patch.object(crq.db_mutations, "upsert_companion_relationship", upsert)
    return get_p, up_p, upsert


def _row(*, relationship_tier=1, session_count=0, affinity=0, session_memories=None):
    return {
        "relationship_tier": relationship_tier,
        "session_count": session_count,
        "affinity": affinity,
        "session_memories": session_memories if session_memories is not None else [],
    }


class TestQuery:
    @pytest.mark.asyncio
    async def test_missing_row_defaults_to_new(self):
        get_p, up_p, _ = _patch_db(None)
        with get_p, up_p:
            res = await crq.query_companion_relationship("p1", "companion_kael")
        assert res == {"tier": "new", "rank": 1, "session_count": 0, "affinity": 0, "unlocks": []}

    @pytest.mark.asyncio
    async def test_trusted_unlocks_gate(self):
        # session_count 6 -> floor rank 3 (trusted); Kael has a trusted reveal in companions.json.
        get_p, up_p, _ = _patch_db(_row(session_count=6))
        with get_p, up_p:
            res = await crq.query_companion_relationship("p1", "companion_kael")
        assert res["tier"] == "trusted"
        assert res["rank"] == 3
        assert len(res["unlocks"]) >= 1


class TestCachedEffectiveRank:
    @pytest.mark.asyncio
    async def test_default_one(self):
        get_p, up_p, _ = _patch_db(None)
        with get_p, up_p:
            assert await crq.cached_effective_rank("p1", "companion_kael") == 1

    @pytest.mark.asyncio
    async def test_floor_plus_affinity_nudge(self):
        # floor rank 3 (session_count 6) + affinity nudge (>=3) = 4.
        get_p, up_p, _ = _patch_db(_row(session_count=6, affinity=3))
        with get_p, up_p:
            assert await crq.cached_effective_rank("p1", "companion_kael") == 4


def _patch_affinity(*, bump_returns):
    """Patch the atomic affinity path: bump returns `bump_returns` (a (new_affinity, session_count)
    tuple, or None for a never-met / no-row companion), cache records its call.
    """
    bump = AsyncMock(return_value=bump_returns)
    cache = AsyncMock()
    return (
        patch.object(crq.db_mutations, "bump_companion_affinity", bump),
        patch.object(crq.db_mutations, "cache_companion_tier", cache),
        bump,
        cache,
    )


class TestApplyErrandAffinity:
    @pytest.mark.asyncio
    async def test_atomic_bump_and_caches_rank(self):
        # bump is the single atomic statement returning (affinity, session_count) = (1, 1).
        bump_p, cache_p, bump, cache = _patch_affinity(bump_returns=(1, 1))
        with bump_p, cache_p:
            new = await crq.apply_errand_affinity("p1", "companion_kael", 1)
        assert new == 1
        assert bump.call_args.args == ("p1", "companion_kael", 1)
        # cache refresh recomputes from the NEW affinity (1 < threshold) -> rank 1.
        assert cache.call_args.args[2] == 1

    @pytest.mark.asyncio
    async def test_never_met_row_is_noop(self):
        # No row -> atomic UPDATE matched nothing -> None -> 0, and no cache write.
        bump_p, cache_p, _bump, cache = _patch_affinity(bump_returns=None)
        with bump_p, cache_p:
            new = await crq.apply_errand_affinity("p1", "companion_kael", 1)
        assert new == 0
        cache.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_clamp_is_delegated_to_atomic_update(self):
        # The >= 0 clamp lives in the SQL (GREATEST); here the bump already returns the clamped 0.
        bump_p, cache_p, _bump, _cache = _patch_affinity(bump_returns=(0, 1))
        with bump_p, cache_p:
            new = await crq.apply_errand_affinity("p1", "companion_kael", -1)
        assert new == 0


class TestHydrate:
    @pytest.mark.asyncio
    async def test_first_meet_increments_to_one(self):
        get_p, up_p, upsert = _patch_db(None)
        with get_p, up_p:
            cs = await crq.hydrate_companion_state("p1", "companion_kael", "Kael")
        assert cs.session_count == 1
        assert cs.affinity == 0
        assert cs.name == "Kael"
        assert upsert.call_args.kwargs["session_count"] == 1

    @pytest.mark.asyncio
    async def test_returning_increments_and_preserves(self):
        get_p, up_p, upsert = _patch_db(_row(session_count=4, affinity=1, session_memories=["m"]))
        with get_p, up_p:
            cs = await crq.hydrate_companion_state("p1", "companion_kael", "Kael")
        assert cs.session_count == 5  # 4 + 1
        assert cs.affinity == 1
        assert cs.session_memories == ["m"]
        assert upsert.call_args.kwargs["session_count"] == 5


class TestCombatIndependence:
    """Relationship NEVER affects combat (spec L871). Guard: combat_init must not import any
    companion_relationship module. The full negative-invariant proof is story-004's."""

    def test_combat_init_does_not_import_relationship(self):
        import combat_init

        src = inspect.getsource(combat_init)
        assert "companion_relationship" not in src
