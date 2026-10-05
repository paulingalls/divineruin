import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

import async_worker_training
import check_tools
import skill_persistence
from async_worker_training import apply_skill_practice_advancement
from check_tools import _check_skill_impl
from tests.test_mechanics_tools import SAMPLE_PLAYER, _make_context, _make_mock_room


def _fake_training():
    """Stub the worker accrual ledger so these skill-practice tests stay hermetic.

    apply_skill_practice_advancement claims the activity via
    db_training.claim_training_accrual before incrementing (idempotency, debt
    b20815f92023); a True claim means 'fresh — apply the increment'.
    """
    mod = MagicMock()
    mod.claim_training_accrual = AsyncMock(return_value=True)
    return mod


def _txn_db():
    """db-module stand-in whose transaction() yields a mock conn (no real DB).

    apply_skill_practice_advancement now wraps claim + counter update in one
    db.transaction() (atomicity, debt b20815f92023); these tests inject it.
    """
    conn = AsyncMock()

    @asynccontextmanager
    async def _transaction():
        yield conn

    module = MagicMock()
    module.transaction = _transaction
    return module


def _install_helper_spy(monkeypatch, spy, real_fn, modules) -> None:
    """Replace every binding of `real_fn` in `modules` with `spy`.

    Catches both module-attr callers (`mod.real_fn(...)`) and from-import
    callers (`from mod import real_fn; real_fn(...)`): the source module's
    attribute is patched, *and* every caller-module attribute that currently
    points at `real_fn` is rebound to `spy`. Identity comparison (`is`) finds
    aliases too (`from mod import real_fn as alias`).
    """
    for module in modules:
        for name, value in list(vars(module).items()):
            if value is real_fn:
                monkeypatch.setattr(module, name, spy)


def _shared_skill_advancement_store():
    """Build mock queries+mutations backed by a single in-memory dict keyed by (player_id, skill)."""
    store: dict[tuple[str, str], dict] = {}

    async def fake_get_single_skill_advancement(
        player_id: str, skill: str, *, conn=None, default_tier="untrained"
    ) -> dict:
        key = (player_id, skill)
        return dict(
            store.get(
                key,
                {"tier": default_tier, "use_counter": 0, "narrative_moment_ready": False},
            )
        )

    async def fake_update_skill_advancement(
        player_id: str, skill: str, new_tier: str, new_use_count: int, *, conn=None
    ) -> None:
        store[(player_id, skill)] = {
            "tier": new_tier,
            "use_counter": new_use_count,
            "narrative_moment_ready": store.get((player_id, skill), {}).get("narrative_moment_ready", False),
        }

    async def fake_clear_narrative_moment(player_id: str, skill: str, *, conn=None) -> None:
        if (player_id, skill) in store:
            store[(player_id, skill)]["narrative_moment_ready"] = False

    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
    queries.get_single_skill_advancement = AsyncMock(side_effect=fake_get_single_skill_advancement)

    mutations = MagicMock()
    mutations.update_skill_advancement = AsyncMock(side_effect=fake_update_skill_advancement)
    mutations.clear_narrative_moment = AsyncMock(side_effect=fake_clear_narrative_moment)

    return store, queries, mutations


class TestHybridCounterSharedRow:
    @pytest.mark.asyncio
    async def test_session_use_and_training_share_skill_advancement_row(self) -> None:
        store, queries, mutations = _shared_skill_advancement_store()
        player_id = "player_1"
        skill = "athletics"

        ctx = _make_context(player_id=player_id, room=_make_mock_room())
        result = json.loads(
            await _check_skill_impl(
                ctx,
                skill=skill,
                difficulty="moderate",
                context_description="climbing",
                queries=queries,
                mutations=mutations,
            )
        )
        assert "error" not in result
        assert store[(player_id, skill)]["use_counter"] == 1

        adv_info = await apply_skill_practice_advancement(
            player_id,
            skill,
            counter_increment=2,
            activity_id="train_hc",
            queries=queries,
            mutations=mutations,
            db_mod=_txn_db(),
            training=_fake_training(),
        )
        assert adv_info is not None
        assert store[(player_id, skill)]["use_counter"] == 3

        assert len(store) == 1
        assert (player_id, skill) in store

    @pytest.mark.asyncio
    async def test_training_starts_proficient_skill_at_trained(self) -> None:
        store, queries, mutations = _shared_skill_advancement_store()

        await apply_skill_practice_advancement(
            "player_1",
            "athletics",
            counter_increment=1,
            activity_id="train_proficient",
            queries=queries,
            mutations=mutations,
            db_mod=_txn_db(),
            training=_fake_training(),
        )

        assert store[("player_1", "athletics")]["tier"] == "trained"

    @pytest.mark.asyncio
    async def test_training_then_session_use_crosses_tier_threshold(self) -> None:
        store, queries, mutations = _shared_skill_advancement_store()
        player_id = "player_1"
        skill = "athletics"

        store[(player_id, skill)] = {"tier": "untrained", "use_counter": 6, "narrative_moment_ready": False}

        adv_info = await apply_skill_practice_advancement(
            player_id,
            skill,
            counter_increment=2,
            activity_id="train_hc",
            queries=queries,
            mutations=mutations,
            db_mod=_txn_db(),
            training=_fake_training(),
        )
        assert adv_info == {"advanced": True, "new_tier": "trained"}
        assert store[(player_id, skill)] == {
            "tier": "trained",
            "use_counter": 8,
            "narrative_moment_ready": False,
        }

        ctx = _make_context(player_id=player_id, room=_make_mock_room())
        result = json.loads(
            await _check_skill_impl(
                ctx,
                skill=skill,
                difficulty="moderate",
                context_description="climbing again",
                queries=queries,
                mutations=mutations,
            )
        )
        assert "error" not in result
        assert store[(player_id, skill)]["use_counter"] == 9
        assert store[(player_id, skill)]["tier"] == "trained"

    @pytest.mark.asyncio
    async def test_both_paths_call_shared_persistence_helper(self, monkeypatch) -> None:
        """Spy on both the source function and its rebound caller namespace."""
        calls: list[tuple[str, str, int]] = []
        real_fn = skill_persistence.apply_skill_use_with_persistence

        async def spy(player_id, skill, counter_increment=1, **kw):
            calls.append((player_id, skill, counter_increment))
            return await real_fn(player_id, skill, counter_increment, **kw)

        _install_helper_spy(monkeypatch, spy, real_fn, [skill_persistence, check_tools, async_worker_training])

        _, queries, mutations = _shared_skill_advancement_store()
        ctx = _make_context(player_id="player_1", room=_make_mock_room())
        await _check_skill_impl(
            ctx,
            skill="athletics",
            difficulty="moderate",
            context_description="x",
            queries=queries,
            mutations=mutations,
        )
        await apply_skill_practice_advancement(
            "player_1",
            "athletics",
            counter_increment=2,
            activity_id="train_hc",
            queries=queries,
            mutations=mutations,
            db_mod=_txn_db(),
            training=_fake_training(),
        )

        assert len(calls) == 2
        assert calls[0][2] == 1  # session-use defaults to 1
        assert calls[1][2] == 2  # training passed 2

    @pytest.mark.asyncio
    async def test_different_skills_use_different_rows(self) -> None:
        store, queries, mutations = _shared_skill_advancement_store()
        player_id = "player_1"

        await apply_skill_practice_advancement(
            player_id,
            "athletics",
            counter_increment=1,
            activity_id="train_hc",
            queries=queries,
            mutations=mutations,
            db_mod=_txn_db(),
            training=_fake_training(),
        )
        await apply_skill_practice_advancement(
            player_id,
            "stealth",
            counter_increment=1,
            activity_id="train_hc",
            queries=queries,
            mutations=mutations,
            db_mod=_txn_db(),
            training=_fake_training(),
        )

        assert store[(player_id, "athletics")]["use_counter"] == 1
        assert store[(player_id, "stealth")]["use_counter"] == 1
        assert len(store) == 2
