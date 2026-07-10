"""M4.4 story-004 — party wipe (AC1/AC4): each member's death is recorded + costed
independently, and each member's resurrection anchor is resolved per-member (story-005).
Also covers the two additive trigger_character_death params (anchor override + waive_cost)
the engine depends on.

Combat is single-player today, so the multi-member path is forward-wired: prod feeds a
1-member party via resurrect_on_defeat; these tests drive resurrect_party_on_defeat directly
with 2 members. Pure injected mutation stubs — no real DB (mirrors story-001/002/003)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from resurrection import (
    resurrect_on_defeat,
    resurrect_party_on_defeat,
    trigger_character_death,
)

_ATTRS = {
    "strength": 14,
    "dexterity": 12,
    "constitution": 13,
    "intelligence": 10,
    "wisdom": 11,
    "charisma": 8,
}

# Death in a still-hostile region -> tier-2 same-region settlement camp_r1. Both members are
# co-located with no last_rested_settlement_id, so per-member resolution coincides on camp_r1.
_LOCATIONS = {
    "battlefield_danger": {"region": "r1", "danger_level": 3},
    "camp_r1": {"region": "r1", "settlement_tier": "village", "danger_level": 1},
    "accord_market_square": {"region": "r9", "settlement_tier": "city", "danger_level": 0, "tags": ["starting_area"]},
}


def _member(player_id, *, patron="none", level=5):
    return {
        "player_id": player_id,
        "class": "warrior",
        "attributes": dict(_ATTRS),
        "level": level,
        "hp": {"current": 0, "max": 60},
        "maxhp_override": 0,
        "location_id": "battlefield_danger",
        "divine_favor": {"patron": patron},
    }


def _death_mutations(counts: dict[str, int]):
    """read_death_history returns each player's prior count (callable side_effect so the
    orchestrator's waive-read and trigger's count-read both resolve per player_id)."""
    m = AsyncMock()
    m.read_death_history = AsyncMock(side_effect=lambda pid, conn=None: {"count": counts[pid], "costs": []})
    m.record_death = AsyncMock()
    return m


class TestTriggerCharacterDeathParams:
    """The two additive params resurrect_party_on_defeat depends on."""

    @pytest.mark.asyncio
    async def test_anchor_override_skips_resolution(self):
        death_mut = _death_mutations({"p1": 0})
        res_mut = AsyncMock()
        ctx = await trigger_character_death(
            _member("p1"),
            _LOCATIONS,
            combat_cleared=False,
            anchor="camp_r1",
            death_mutations=death_mut,
            mutations=res_mut,
            conn=object(),
        )
        # Anchor is the supplied one, revived there — resolution was bypassed.
        assert ctx["anchor"] == "camp_r1"
        assert res_mut.revive_player.call_args.args[1] == "camp_r1"

    @pytest.mark.asyncio
    async def test_waive_cost_skips_record_and_cost_but_revives(self):
        death_mut = _death_mutations({"p1": 0})
        res_mut = AsyncMock()
        ctx = await trigger_character_death(
            _member("p1"),
            _LOCATIONS,
            combat_cleared=False,
            waive_cost=True,
            death_mutations=death_mut,
            mutations=res_mut,
            conn=object(),
        )
        # Waived: not recorded, not counted, no attribute/maxHP cost — but still revived.
        death_mut.record_death.assert_not_awaited()
        res_mut.apply_attribute_penalty.assert_not_awaited()
        res_mut.apply_maxhp_override_delta.assert_not_awaited()
        res_mut.revive_player.assert_awaited_once()
        assert ctx["tier"] == "waived"
        assert ctx["death_count"] == 0  # unchanged — the waived death does not count


class TestResurrectPartyOnDefeat:
    @pytest.mark.asyncio
    async def test_each_member_records_and_pays_own_tier_at_coincident_anchor(self):
        """AC1: every member's death is recorded and costed by their OWN running count."""
        # p_a on its 1st death (gentle, no penalty); p_b on its 3rd (severe, primary -1).
        death_mut = _death_mutations({"p_a": 0, "p_b": 2})
        res_mut = AsyncMock()
        content = MagicMock(get_all_locations=AsyncMock(return_value=_LOCATIONS))

        contexts = await resurrect_party_on_defeat(
            [_member("p_a"), _member("p_b")],
            combat_cleared=False,
            content_queries=content,
            death_mutations=death_mut,
            mutations=res_mut,
            conn=object(),
        )

        assert [c["tier"] for c in contexts] == ["gentle", "severe"]
        assert death_mut.record_death.await_count == 2  # both non-patron deaths recorded
        # Both resolve to camp_r1 independently — co-located, no divergent last-rested anchor.
        assert {c["anchor"] for c in contexts} == {"camp_r1"}
        anchors = [call.args[1] for call in res_mut.revive_player.call_args_list]
        assert anchors == ["camp_r1", "camp_r1"]

    @pytest.mark.asyncio
    async def test_mortaen_first_death_free_non_patron_pays(self):
        """AC4: a Mortaen patron (first-ever death) is waived/un-counted while the non-patron
        (2nd death) pays the standard moderate cost; both resolve to the same anchor
        (co-located, no divergent last-rested)."""
        death_mut = _death_mutations({"p_mort": 0, "p_non": 1})
        res_mut = AsyncMock()
        content = MagicMock(get_all_locations=AsyncMock(return_value=_LOCATIONS))

        contexts = await resurrect_party_on_defeat(
            [_member("p_mort", patron="mortaen"), _member("p_non")],
            combat_cleared=False,
            content_queries=content,
            death_mutations=death_mut,
            mutations=res_mut,
            conn=object(),
        )

        mort, non = contexts
        # Mortaen: waived — not recorded, count UNCHANGED at 0 (the reviewer's un-counting check).
        assert mort["tier"] == "waived" and mort["death_count"] == 0
        # Non-patron: 2nd death -> moderate, -1 to lowest attribute (charisma).
        assert non["tier"] == "moderate" and non["death_count"] == 2
        # Only the non-patron's death is recorded (the patron's is free).
        recorded_ids = [call.args[0] for call in death_mut.record_death.call_args_list]
        assert recorded_ids == ["p_non"]
        penalized = res_mut.apply_attribute_penalty.call_args
        assert penalized.args[:3] == ("p_non", "charisma", -1)
        assert {c["anchor"] for c in contexts} == {"camp_r1"}


class TestResurrectOnDefeatDelegates:
    @pytest.mark.asyncio
    async def test_single_player_path_returns_one_context(self):
        """resurrect_on_defeat (the live single-player defeat path) delegates to the party
        engine with a 1-member party and returns the single context dict."""
        death_mut = _death_mutations({"p1": 0})
        res_mut = AsyncMock()
        content = MagicMock(get_all_locations=AsyncMock(return_value=_LOCATIONS))

        ctx = await resurrect_on_defeat(
            _member("p1"),
            combat_cleared=False,
            content_queries=content,
            death_mutations=death_mut,
            mutations=res_mut,
            conn=object(),
        )

        assert isinstance(ctx, dict)
        assert ctx["anchor"] == "camp_r1" and ctx["tier"] == "gentle"
        res_mut.revive_player.assert_awaited_once()
