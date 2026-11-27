"""Rally eligibility, payment and rollback through registered commands."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_marshal_rally import RALLY, cast_rally, declare_round, enter_fight, player, rally
from acceptance.test_marshal_rally import fight as fight
from acceptance.test_marshal_rally import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_martial_core_kit import weapon_attack
from acceptance.test_self_buff_electives import discovered, receipt
from acceptance.test_war_cry import point
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from voice_condition_fixtures import participant

import combat_spatial
import conditions
import db
import db_mutations
import db_queries
import temp_hp


@pytest.mark.parametrize(
    ("exclusion", "reason"),
    [(None, None), ("range", "beyond 30 ft"), ("deafened", "cannot hear"), ("silence", "cannot hear")],
)
async def test_recipient_range_and_hearing(fight: MawlingHarness, exclusion: str | None, reason: str | None) -> None:
    marshal, control, listener = fight.players
    await enter_fight(fight)
    state = await fight.reload()
    foe = next(p for p in state.participants if p.type == "enemy")
    combat_spatial.place(state, foe.id, point(5))
    combat_spatial.place(state, listener, point(31 if exclusion == "range" else 30))
    target = participant(state, listener)
    if exclusion == "deafened":
        target.conditions = conditions.apply_condition(target.conditions, "deafened", source="test")
    if exclusion == "silence":
        combat_spatial.require_spatial(state)["zones"]["silence"] = {
            "kind": "silence",
            "center_id": listener,
            "radius_ft": 1,
        }
    await fight.persist()
    result = await cast_rally(fight)
    outcomes = {row["recipient_id"]: row for row in result["rally_results"]}
    assert outcomes[control]["granted"] == 5
    assert outcomes[listener]["reason"] == reason
    assert outcomes[listener]["granted"] == (0 if reason else 5)
    assert (await player(listener)).get("temp_hp", 0) == outcomes[listener]["granted"]
    saved = await fight.reload()
    assert participant(saved, listener).temp_hp == outcomes[listener]["granted"]
    for excluded in (marshal, foe.id):
        assert excluded not in outcomes and participant(saved, excluded).temp_hp == 0


async def test_silent_source_refuses_and_no_listeners_waste_rally_unpaid(fight: MawlingHarness) -> None:
    marshal = fight.players[0]
    await enter_fight(fight)
    state = await fight.reload()
    zones = combat_spatial.require_spatial(state)["zones"]
    zones["silence"] = {"kind": "silence", "center_id": marshal, "radius_ft": 1}
    await fight.persist()
    before = await fight.snapshot()
    focus = (await player(marshal))["focus"]
    assert "silenced and cannot speak" in await declare_round(fight, rally(marshal), error=True)
    assert await fight.snapshot() == before
    state = await fight.reload()
    del combat_spatial.require_spatial(state)["zones"]["silence"]
    allies = [p for p in state.participants if p.is_ally and p.id != marshal]
    for ally in allies:
        combat_spatial.place(state, ally.id, point(35))
    await fight.persist()
    result = await cast_rally(fight)
    assert result["resolved"] is False and result["target_ids"] == []
    assert {row["recipient_id"]: row["reason"] for row in result["rally_results"]} == {
        p.id: "beyond 30 ft" for p in allies
    }
    assert (await player(marshal))["focus"] == focus
    state = await fight.reload()
    combat_spatial.place(state, fight.players[1], point(30))
    await fight.persist()
    assert (await cast_rally(fight))["target_ids"] == [fight.players[1]]


async def test_rally_preserves_higher_and_equal_pools(fight: MawlingHarness) -> None:
    _, higher, equal = fight.players
    await enter_fight(fight)
    state = await fight.reload()
    companion = next(p for p in state.participants if p.type == "companion")
    companion.temp_hp = 8
    async with db.transaction() as conn:
        locked = (await db_queries.get_players_for_update([higher], conn=conn))[higher]
        await temp_hp.grant(higher, locked, 8, participant=participant(state, higher), conn=conn)
    await fight.persist()
    for expected in (5, 0):
        outcomes = {r["recipient_id"]: r for r in (await cast_rally(fight))["rally_results"]}
        assert {pid: outcomes[pid]["granted"] for pid in (higher, equal, companion.id)} == {
            higher: 0,
            equal: expected,
            companion.id: 0,
        }
        saved = await fight.reload()
        assert (await player(higher))["temp_hp"] == participant(saved, higher).temp_hp == 8
        assert (await player(equal))["temp_hp"] == participant(saved, equal).temp_hp == 5
        assert participant(saved, companion.id).temp_hp == 8


async def test_exploration_hides_and_refuses_rally_before_payment(fight: MawlingHarness) -> None:
    marshal = fight.players[0]
    query = await fight.command("query_info", {"kind": "abilities"})
    ids = {row["id"] for row in query["abilities"]}
    assert RALLY not in ids and "marshal_direct_strike" in ids
    before = await player(marshal)
    refusal = await fight.command("activate", {"id": RALLY}, error=True)
    assert f"declare {RALLY} in a combat phase" in refusal
    assert await player(marshal) == before
    refusal = await fight.command("declare_phase", {"declarations": [rally(marshal)]}, error=True)
    assert "combat" in refusal.lower()
    other = await fight.command("activate", {"id": "marshal_direct_strike"})
    assert other["deducted"]["focus"] == 2
    await enter_fight(fight)
    assert (await discovered(fight, RALLY))["combat"] is True
    refusal = await fight.command("activate", {"id": RALLY}, error=True)
    assert f"declare {RALLY} in the combat phase" in refusal
    assert (await cast_rally(fight))["resolved"] is True


async def test_rally_rolls_back_rows_and_phase_when_save_fails(
    fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    await enter_fight(fight)
    await declare_round(fight, rally(fight.players[0]))
    before = await fight.snapshot()
    before_events = published_payloads(fight.sd.room)

    async def fail_after_grant(combat_id: str, state: dict, *, conn=None) -> None:
        row = await db_queries.get_player(fight.players[1], conn=conn)
        assert row is not None and row["temp_hp"] == 5
        raise ToolError("Rally combat save failed")

    with monkeypatch.context() as patch:
        patch.setattr(db_mutations, "save_combat_state", fail_after_grant)
        assert "Rally combat save failed" in await fight.command("resolve_phase", {}, error=True)
    assert await fight.snapshot() == before
    assert published_payloads(fight.sd.room) == before_events
    await fight.drain()
    for ally in fight.players[1:]:
        assert (await player(ally))["temp_hp"] == 5


async def test_enemy_cannot_use_a_participant_temp_hp_field(fight: MawlingHarness) -> None:
    marshal = fight.players[0]
    await enter_fight(fight)
    state = await fight.reload()
    foe = participant(state, "mawling_1")
    foe.hp_current = foe.hp_max = 30
    foe.temp_hp = 8
    combat_spatial.place(state, foe.id, point(5))
    await fight.persist()
    await declare_round(fight, weapon_attack(marshal, foe.id, ""))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(17)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        hit = receipt(await fight.drain(), marshal)
    assert hit["hit"] and 0 < hit["damage"] < 8
    assert hit["temp_hp_absorbed"] == 0
    assert participant(await fight.reload(), foe.id).hp_current == 30 - hit["damage"]
