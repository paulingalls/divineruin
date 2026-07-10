"""M14 story-005 — per-member resurrection anchor engine. `resurrect_party_on_defeat`
resolves each member's anchor independently (resolve_resurrection_anchor is per-member,
including each member's own `last_rested_settlement_id`), instead of forcing a single
`party[0]`-derived anchor onto every member. Tier-3 (last-rested) is where members can
diverge; tiers 1/2/4 still coincide when members are co-located. Pure injected mutation
stubs — no real DB (mirrors test_party_wipe.py)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from resurrection import resurrect_on_defeat, resurrect_party_on_defeat

_ATTRS = {
    "strength": 14,
    "dexterity": 12,
    "constitution": 13,
    "intelligence": 10,
    "wisdom": 11,
    "charisma": 8,
}

# Death region has no settlement-tier location (tier-2 empty) and combat isn't cleared /
# danger is high (tier-1 fails), so tier-3 (last-rested, per-member) decides.
_LOCATIONS = {
    "battlefield_danger": {"region": "r1", "danger_level": 3},
    "home_a": {"region": "r9", "danger_level": 0},
    "home_b": {"region": "r9", "danger_level": 0},
    "accord_market_square": {"region": "r9", "danger_level": 0, "tags": ["starting_area"]},
}


def _member(player_id, *, last_rested=None, patron="none", level=5):
    return {
        "player_id": player_id,
        "class": "warrior",
        "attributes": dict(_ATTRS),
        "level": level,
        "hp": {"current": 0, "max": 60},
        "maxhp_override": 0,
        "location_id": "battlefield_danger",
        "last_rested_settlement_id": last_rested,
        "divine_favor": {"patron": patron},
    }


def _death_mutations(counts: dict[str, int]):
    m = AsyncMock()
    m.read_death_history = AsyncMock(side_effect=lambda pid, conn=None: {"count": counts[pid], "costs": []})
    m.record_death = AsyncMock()
    return m


class TestPerMemberAnchor:
    @pytest.mark.asyncio
    async def test_divergent_last_rested_anchors_resolve_per_member(self):
        """AC1/AC4: members with divergent last-rested anchors revive at their OWN anchor,
        not a shared party[0]-derived one."""
        death_mut = _death_mutations({"p_a": 0, "p_b": 0})
        res_mut = AsyncMock()
        content = MagicMock(get_all_locations=AsyncMock(return_value=_LOCATIONS))

        contexts = await resurrect_party_on_defeat(
            [_member("p_a", last_rested="home_a"), _member("p_b", last_rested="home_b")],
            combat_cleared=False,
            content_queries=content,
            death_mutations=death_mut,
            mutations=res_mut,
            conn=object(),
        )

        assert [c["anchor"] for c in contexts] == ["home_a", "home_b"]
        anchors = [call.args[1] for call in res_mut.revive_player.call_args_list]
        assert anchors == ["home_a", "home_b"]

    @pytest.mark.asyncio
    async def test_per_member_death_cost_and_count_independent(self):
        """AC3: distinct per-player death histories -> each member's record_death / returned
        death count is per member (unaffected by the per-member anchor change)."""
        death_mut = _death_mutations({"p_a": 0, "p_b": 2})
        res_mut = AsyncMock()
        content = MagicMock(get_all_locations=AsyncMock(return_value=_LOCATIONS))

        contexts = await resurrect_party_on_defeat(
            [_member("p_a", last_rested="home_a"), _member("p_b", last_rested="home_b")],
            combat_cleared=False,
            content_queries=content,
            death_mutations=death_mut,
            mutations=res_mut,
            conn=object(),
        )

        assert [c["tier"] for c in contexts] == ["gentle", "severe"]
        assert [c["death_count"] for c in contexts] == [1, 3]
        assert death_mut.record_death.await_count == 2


class TestSoloPartyParity:
    @pytest.mark.asyncio
    async def test_solo_party_matches_prior_shared_pick(self):
        """AC2: a 1-member party via resurrect_on_defeat returns the single death context
        unchanged — per-member resolution on a solo party is identical to the old party[0]
        shared pick."""
        death_mut = _death_mutations({"p1": 0})
        res_mut = AsyncMock()
        content = MagicMock(get_all_locations=AsyncMock(return_value=_LOCATIONS))

        ctx = await resurrect_on_defeat(
            _member("p1", last_rested="home_a"),
            combat_cleared=False,
            content_queries=content,
            death_mutations=death_mut,
            mutations=res_mut,
            conn=object(),
        )

        assert ctx["anchor"] == "home_a"
        res_mut.revive_player.assert_awaited_once()
