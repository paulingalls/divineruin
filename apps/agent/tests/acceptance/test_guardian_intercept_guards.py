from unittest.mock import patch

import pytest
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_guardian_intercept import INTERCEPT, WALL, activate, blows, opening, pools, tool_receipt
from acceptance.test_guardian_intercept import fight as fight
from acceptance.test_guardian_intercept import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_opportunity_strike import participant, stamina

import combat_hold
import reaction_spend


@pytest.mark.parametrize(
    "scenario, actor_index, why",
    [
        ("range", 0, "within 5 ft"),
        ("self", 1, "another ally"),
    ],
)
async def test_refused_intercept(fight: MawlingHarness, actor_index: int, why: str) -> None:
    actor = fight.players[actor_index]
    before = await pools(fight)
    start = await stamina(actor)
    window = await opening(fight)
    refused = await activate(fight, actor)
    after = await stamina(actor)
    state = await fight.reload()
    assert after == start
    assert not reaction_spend.is_spent(state.reactions_available[actor])
    packets = await fight.drain()
    assert await pools(fight) == [before[0], (before[1][0] - 7, 0), before[2]]
    assert blows(packets)[0]["damage"] == 7
    assert refused.is_error and why in refused.output
    assert all(r["id"] != INTERCEPT or r["actor_id"] != actor for r in window["reactions"])


@pytest.mark.parametrize("scenario", ["duplicate"])
@pytest.mark.parametrize("first_index", [0, 2])
async def test_first_intercept_wins(fight: MawlingHarness, first_index: int) -> None:
    first, second = fight.players[first_index], fight.players[2 - first_index]
    before = await pools(fight)
    start_first, start_second = await stamina(first), await stamina(second)
    await opening(fight)
    accepted = await activate(fight, first)
    assert not accepted.is_error, accepted.output
    await fight.reload()
    refused = await activate(fight, second)
    assert await stamina(first) == start_first - 3
    assert await stamina(second) == start_second
    state = await fight.reload()
    assert not reaction_spend.is_spent(state.reactions_available[second])
    packets = await fight.drain()
    before[first_index] = (before[first_index][0] - 7, 0)
    assert await pools(fight) == before
    assert blows(packets)[0]["damage_target_id"] == first
    assert [p["actor_id"] for p in packets if p.get("mechanical_effect") == "damage_intercepted"] == [first]
    assert refused.is_error and "already intercepted" in refused.output


@pytest.mark.parametrize("scenario", ["duplicate"])
@pytest.mark.parametrize("legacy_count", [1, 2])
async def test_pre_transfer_spends_keep_their_original_outcome(fight: MawlingHarness, legacy_count: int) -> None:
    await opening(fight)
    guardian, _, other = fight.players
    before = await pools(fight)
    state = await fight.reload()
    window = state.open_window
    assert window is not None
    for actor in (guardian, other)[:legacy_count]:
        state.reactions_available[actor] = {
            "spent": True,
            "ability_id": INTERCEPT,
            "held_seq": state.held_actions[0]["seq"],
            "window_id": window["id"],
            "stage": window["stage"],
        }
    await fight.persist()
    if legacy_count == 1:
        start = await stamina(other)
        accepted = await activate(fight, other)
        assert await stamina(other) == start - 3
        assert not accepted.is_error, accepted.output
    packets = await fight.drain()
    hit_index = 2 if legacy_count == 1 else 1
    before[hit_index] = (before[hit_index][0] - 7, 0)
    assert await pools(fight) == before
    assert blows(packets)[0]["damage"] == 7
    assert [
        p["mechanical_effect"] for p in packets if p["actor_id"] == guardian and p.get("ability_id") == INTERCEPT
    ] == [None]


@pytest.mark.parametrize("scenario", ["duplicate_followup"])
async def test_another_guardian_can_intercept_the_next_held_hit(fight: MawlingHarness) -> None:
    first, _, second = fight.players
    before = await pools(fight)
    first_window = await opening(fight)
    assert not (await activate(fight, first)).is_error
    result = await fight.command("resolve_phase", {})
    second_window = result["next"]["waiting_on"]
    assert second_window["window_id"] != first_window["window_id"]
    start = await stamina(second)
    activated = await activate(fight, second)
    assert await stamina(second) == start - 3
    assert not activated.is_error
    packets = [*result["packets"], *(await fight.drain())]
    assert [p["damage_target_id"] for p in blows(packets)] == [first, second]
    assert await pools(fight) == [(before[0][0] - 7, 0), before[1], (before[2][0] - 7, 0)]


@pytest.mark.parametrize("scenario", ["structure"])
async def test_a_struck_wall_is_not_an_ally(fight: MawlingHarness) -> None:
    guardian = fight.players[0]
    before = await pools(fight)
    wall_hp = participant(await fight.reload(), WALL).hp_current
    start = await stamina(guardian)
    await fight.command("resolve_phase", {})
    result = await fight.command("resolve_phase", {})
    window = result["next"]["waiting_on"]
    if window is not None:
        await activate(fight, guardian)
    assert await stamina(guardian) == start
    if result["next"]["phase"] != "declaration":
        await fight.drain()
    assert await pools(fight) == before
    assert participant(await fight.reload(), WALL).hp_current == wall_hp - 7
    assert window is None


@pytest.mark.parametrize("scenario", ["plain"])
async def test_missing_damage_route_rolls_back_the_held_hit(fight: MawlingHarness) -> None:
    guardian = fight.players[0]
    before = await pools(fight)
    await opening(fight)
    assert not (await activate(fight, guardian)).is_error
    resolve = combat_hold._resolve_one_packet

    async def resolve_without_transfer(*args, **kwargs) -> dict:
        kwargs.pop("damage_target")
        return await resolve(*args, **kwargs)

    with patch.object(combat_hold, "_resolve_one_packet", resolve_without_transfer):
        result = await tool_receipt(fight, guardian, "resolve_phase", {})
    assert await pools(fight) == before
    assert result.is_error, result.output
