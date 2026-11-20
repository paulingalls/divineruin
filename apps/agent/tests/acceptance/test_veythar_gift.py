"""Lorekeeper's Insight through registered exploration tools."""

import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from acceptance._capstone_helpers import _d20
from acceptance.journal_walk import ITEM
from acceptance.rest_walk import RestWalk
from acceptance.veythar_walk import CALL, GIFT, GiftWalk, favor

import db_queries
import event_types as E
from _gods_content import load_gods
from participant_lifecycle import PartyLifecycle
from session_startup import GameplayInputOwner


def test_authored_gift_is_active():
    gift = next(g["layer_1_gift"] for g in load_gods() if g["god_id"] == "veythar")
    assert (gift["id"], gift["status"], gift["recharge"]) == (GIFT, "active", "short_rest")


@pytest.mark.parametrize("skill", ["arcana", "history", "investigation", "nature", "religion"])
def test_failed_knowledge_offers_optional_reroll(harness, skill):
    async def scenario():
        walk = await GiftWalk().start(harness)
        result = await walk.skill(skill)
        assert CALL in result["reroll_offer"]
        state = await walk.state()
        assert state["spent"] is False
        assert state["pending"]["skill"] == skill
        assert state["pending"]["dc"] == result["dc"]
        assert state["pending"]["context_description"] == result["context"]

    harness.run_sync(scenario())


@pytest.mark.parametrize("replacement", [20, 1])
def test_replacement_stands_and_spends_once(harness, replacement):
    async def scenario():
        walk = await GiftWalk().start(harness)
        assert "failed check" in (await walk.use(error=True)).lower()
        initial = await walk.skill()
        assert CALL in initial["reroll_offer"]
        advancement = await db_queries.get_single_skill_advancement(walk.player, "arcana")
        await walk.connect(harness)
        result = await walk.use(replacement)
        assert result["roll"] == replacement
        assert result["outcome"] == ("success" if replacement == 20 else "failure")
        assert result["dc"] == initial["dc"]
        assert result["context"] == initial["context"]
        assert "reroll_offer" not in result
        assert await db_queries.get_single_skill_advancement(walk.player, "arcana") == advancement
        assert [e for e in walk.events if e["type"] == E.DICE_ROLL][-1]["roll"] == replacement
        assert await walk.state() == {"spent": True, "pending": None}
        row = await walk.row()
        assert row["keepsake"] == "unchanged" and row["patron_gifts"]["other"] == {"x": 1}
        assert "short rest" in (await walk.use(error=True)).lower()
        assert "reroll_offer" not in await walk.skill()
        assert await walk.state() == {"spent": True, "pending": None}

    harness.run_sync(scenario())


@pytest.mark.parametrize("replacement", [20, 1])
def test_discovery_reconnect_rewards_original_journal(harness, replacement):
    async def scenario():
        walk = await GiftWalk().start(harness)
        failed = await walk.search()
        assert CALL in failed["reroll_offer"] and "element_id" not in failed
        assert f"{walk.player}:investigation:{ITEM}" in walk.sd.attempted_discoveries
        assert (await walk.state())["pending"]["element_id"] == ITEM
        await walk.connect(harness)
        walk.events.clear()
        result = await walk.use(replacement)
        assert result["target"] == failed["target"] and result["dc"] == failed["dc"]
        if replacement == 20:
            assert result["element_id"] == ITEM
            await walk.rewarded(result)
            assert any(e["type"] == E.HIDDEN_REVEALED for e in walk.events)
            assert any(e["type"] == E.PLAY_SOUND for e in walk.events)
        else:
            assert result["outcome"] == "not_found" and "element_id" not in result
            assert await walk.quantity() == 0 and await walk.marker() == 3
            assert not (await walk.row()).get("flags", {}).get(ITEM + ".discovered")
        assert "short rest" in (await walk.use(error=True)).lower()
        assert await walk.quantity() == (1 if replacement == 20 else 0)

    harness.run_sync(scenario())


@pytest.mark.parametrize("face", [20, 1])
def test_non_item_discovery_uses_original_element(harness, face):
    async def scenario():
        walk = await GiftWalk().start(harness)
        failed = await walk.search(skill="arcana", target="archway")
        assert CALL in failed["reroll_offer"]
        element = (await walk.state())["pending"]["element_id"]
        result = await walk.use(face)
        assert result["outcome"] == ("discovered" if face == 20 else "not_found")
        assert (await walk.row()).get("flags", {}).get(element + ".discovered", False) is (face == 20)
        assert await walk.quantity() == 0 and await walk.marker() == 3

    harness.run_sync(scenario())


def test_empty_search_keeps_no_candidate_after_reconnect(harness):
    async def scenario():
        walk = await GiftWalk().start(harness)
        failed = await walk.search(skill="investigation", target="research station")
        assert CALL in failed["reroll_offer"]
        # The attempt gate now leaves an empty search; reroll must not reselect on reconnect.
        empty = await walk.search(skill="investigation", target="research station")
        assert CALL in empty["reroll_offer"]
        assert (await walk.state())["pending"]["element_id"] is None
        await walk.connect(harness)
        result = await walk.use()
        assert result["dc"] == 13 and result["outcome"] == "not_found"
        assert "element_id" not in result
        assert await walk.quantity() == 0 and await walk.marker() == 3

    harness.run_sync(scenario())


def test_exclusions_and_pending_policy(harness):
    async def scenario():
        positive = await GiftWalk().start(harness)
        assert CALL in (await positive.skill())["reroll_offer"]
        pending = await positive.state()
        await positive.skill(face=20)
        await positive.skill("athletics")
        assert await positive.state() == pending
        for mode, skill, face, patron in [
            ("skill", "arcana", 20, "veythar"),
            ("skill", "athletics", 2, "veythar"),
            ("skill", "arcana", 2, "valdris"),
            ("discover", "perception", 2, "veythar"),
            ("discover", "history", 20, "veythar"),
        ]:
            walk = await GiftWalk().start(harness)
            await walk.patch(divine_favor=favor(patron))
            if mode == "discover":
                # The entrance's scout token answers a first search with no roll. Find it so this search rolls.
                await walk.discover(target="rubble")
            result = await (walk.skill(skill, face) if mode == "skill" else walk.search(face, skill=skill))
            assert "reroll_offer" not in result and await walk.state() is None
        walk = await GiftWalk().start(harness)
        with patch("check_resolution.dice_roll", return_value=_d20(1)) as rolls:
            result = await walk.command(
                "check",
                {
                    "roll": {
                        "kind": "skill",
                        "skill": "arcana",
                        "difficulty": "extreme",
                        "context_description": "Impossible lore",
                        "hearing_only": False,
                    }
                },
            )
        assert result["outcome"] == "automatic_failure" and rolls.call_count == 0
        assert "reroll_offer" not in result and await walk.state() is None

    harness.run_sync(scenario())


def test_rest_recharges_only_authored_type_and_party_recipient(harness):
    async def scenario():
        walk = await GiftWalk().start(harness)
        await walk.skill()
        await walk.use()
        await walk.connect(harness)
        assert "spent" in await walk.use(error=True)
        await walk.patch(
            location_id="millhaven_inn", stamina={"current": 1, "max": 10}, focus={"current": 1, "max": 10}
        )
        await walk.connect(harness)
        # Use RestWalk's registered rest command with this gift scenario's real session.
        walk.validator = lambda *_: None
        receipt = await RestWalk.command(cast(Any, walk), "long")
        assert not receipt.is_error, receipt.output
        assert await walk.state() == {"spent": False, "pending": None}
        await walk.connect(harness)
        walk.add_guest()
        await walk.pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
            walk.guest,
            json.dumps(
                {
                    "location_id": "millhaven_inn",
                    "stamina": {"current": 1, "max": 10},
                    "divine_favor": favor("veythar"),
                    "patron_gifts": {GIFT: {"spent": True, "pending": None}},
                }
            ),
        )
        room = cast(MagicMock, walk.sd.room)
        room.remote_participants = {pid: SimpleNamespace(identity=pid) for pid in (walk.player, walk.guest)}
        lifecycle = PartyLifecycle(room, walk.sd, queries=None, resonance_mod=None, concentration_mod=None)
        harness.stack.callback(lambda: harness.run_sync(lifecycle.aclose()))
        walk.sd.multiplayer_owner = GameplayInputOwner(lifecycle, MagicMock(), MagicMock())
        receipt = await RestWalk.command(cast(Any, walk), "short")
        assert not receipt.is_error, receipt.output
        assert await walk.state() == {"spent": False, "pending": None}
        guest = await db_queries.get_player(walk.guest)
        assert guest is not None
        assert guest["patron_gifts"][GIFT] == {"spent": False, "pending": None}
        await walk.skill()
        assert (await walk.state())["pending"] is not None
        receipt = await RestWalk.command(cast(Any, walk), "short")
        assert not receipt.is_error, receipt.output
        assert await walk.state() == {"spent": False, "pending": None}
        await walk.skill()
        await walk.use()
        assert (await walk.row())["patron_gifts"]["other"] == {"x": 1}

    harness.run_sync(scenario())


def test_reroll_uses_current_modifiers_and_consumes_current_inspiration(harness):
    async def scenario():
        walk = await GiftWalk().start(harness)
        await walk.patch(conditions=[{"type": "inspired", "duration": 2, "source": "ally"}])
        with patch("condition_bonus.dice_roll", return_value=_d20(1)):
            failed = await walk.skill()
        assert CALL in failed["reroll_offer"]
        assert (await walk.row())["conditions"] == []
        await walk.patch(
            attributes={"intelligence": 30}, conditions=[{"type": "inspired", "duration": 2, "source": "new_ally"}]
        )
        with patch("condition_bonus.dice_roll", return_value=_d20(3)) as bonus:
            replacement = await walk.use(6)
        assert bonus.call_count == 1
        assert replacement["outcome"] == "success" and replacement["modifier"] > failed["modifier"]
        assert (await walk.row())["conditions"] == []

    harness.run_sync(scenario())


@pytest.mark.parametrize("obstruction", ["moved", "database_moved", "session_moved", "discovered", "malformed"])
def test_invalid_pending_refuses_without_spending(harness, obstruction):
    async def scenario():
        walk = await GiftWalk().start(harness)
        await walk.search()
        if obstruction in {"moved", "database_moved"}:
            await walk.patch(location_id="millhaven")
            if obstruction == "moved":
                await walk.connect(harness)
        elif obstruction == "session_moved":
            walk.sd.location_id = "millhaven"
        elif obstruction == "discovered":
            await walk.patch(flags={ITEM + ".discovered": True})
        else:
            await walk.patch(patron_gifts={GIFT: {"spent": "false", "pending": None}})
        before = await walk.durable()
        await walk.use(error=True)
        assert await walk.durable() == before

    harness.run_sync(scenario())
