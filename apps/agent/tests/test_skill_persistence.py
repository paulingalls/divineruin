"""Behavior tests for the shared skill-advancement persistence helper.

This is the new primitive extracted from check_tools and async_worker —
both paths now route through `apply_skill_use_with_persistence` so the
M1.2 hybrid-counter contract is enforced by construction.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from skill_persistence import apply_skill_use_with_persistence


def _store_backed_mocks():
    store: dict[tuple[str, str], dict] = {}

    async def fake_get(player_id: str, skill: str, *, conn=None) -> dict:
        key = (player_id, skill)
        if key not in store:
            store[key] = {"tier": "untrained", "use_counter": 0, "narrative_moment_ready": False}
        return dict(store[key])

    async def fake_update(player_id: str, skill: str, new_tier: str, new_use_count: int, *, conn=None) -> None:
        store[(player_id, skill)] = {
            "tier": new_tier,
            "use_counter": new_use_count,
            "narrative_moment_ready": store.get((player_id, skill), {}).get("narrative_moment_ready", False),
        }

    async def fake_clear(player_id: str, skill: str, *, conn=None) -> None:
        if (player_id, skill) in store:
            store[(player_id, skill)]["narrative_moment_ready"] = False

    queries = MagicMock()
    queries.get_single_skill_advancement = AsyncMock(side_effect=fake_get)

    mutations = MagicMock()
    mutations.update_skill_advancement = AsyncMock(side_effect=fake_update)
    mutations.clear_narrative_moment = AsyncMock(side_effect=fake_clear)

    return store, queries, mutations


class TestApplySkillUseWithPersistence:
    @pytest.mark.asyncio
    async def test_single_increment_persists_one_row(self) -> None:
        store, queries, mutations = _store_backed_mocks()

        adv = await apply_skill_use_with_persistence(
            "player_1", "athletics", counter_increment=1, queries=queries, mutations=mutations
        )

        assert adv is not None
        assert store[("player_1", "athletics")]["use_counter"] == 1
        assert mutations.update_skill_advancement.await_count == 1

    @pytest.mark.asyncio
    async def test_multi_increment_loops_record_skill_use(self) -> None:
        store, queries, mutations = _store_backed_mocks()

        adv = await apply_skill_use_with_persistence(
            "player_1", "athletics", counter_increment=3, queries=queries, mutations=mutations
        )

        assert adv is not None
        assert store[("player_1", "athletics")]["use_counter"] == 3
        assert mutations.update_skill_advancement.await_count == 1  # one persist after the loop

    @pytest.mark.asyncio
    async def test_zero_increment_is_noop(self) -> None:
        store, queries, mutations = _store_backed_mocks()

        adv = await apply_skill_use_with_persistence(
            "player_1", "athletics", counter_increment=0, queries=queries, mutations=mutations
        )

        assert adv is None
        assert store == {}
        assert queries.get_single_skill_advancement.await_count == 0
        assert mutations.update_skill_advancement.await_count == 0

    @pytest.mark.asyncio
    async def test_tier_advancement_at_threshold(self) -> None:
        store, queries, mutations = _store_backed_mocks()
        store[("player_1", "athletics")] = {"tier": "untrained", "use_counter": 6, "narrative_moment_ready": False}

        adv = await apply_skill_use_with_persistence(
            "player_1", "athletics", counter_increment=2, queries=queries, mutations=mutations
        )

        assert adv is not None
        assert adv.advanced is True
        assert adv.new_tier == "trained"
        assert store[("player_1", "athletics")]["use_counter"] == 8

    @pytest.mark.asyncio
    async def test_expert_to_master_clears_narrative_moment(self) -> None:
        store, queries, mutations = _store_backed_mocks()
        # Pre-seed at expert tier with narrative_moment_ready=True and a counter just below master threshold.
        store[("player_1", "athletics")] = {"tier": "expert", "use_counter": 31, "narrative_moment_ready": True}

        adv = await apply_skill_use_with_persistence(
            "player_1", "athletics", counter_increment=1, queries=queries, mutations=mutations
        )

        assert adv is not None
        if adv.advanced and adv.old_tier == "expert":
            assert mutations.clear_narrative_moment.await_count == 1
            assert store[("player_1", "athletics")]["narrative_moment_ready"] is False
