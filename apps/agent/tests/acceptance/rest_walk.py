"""Registered rest commands against committed character rows and client bytes."""

import copy
import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

from acceptance.greyvale_arc_walk_harness import ArcWalk
from acceptance.seeds import seed_player
from pytest_bdd import given, parsers, then, when

import db
import db_content_queries
import db_queries
import event_types as E
from combat_state import CombatState
from participant_lifecycle import PartyLifecycle
from rest_mechanics import apply_long_rest, apply_short_rest
from session_data import SessionData
from session_startup import GameplayInputOwner


class RestWalk(ArcWalk):
    resting = False
    primary_hp_bonus = 0

    async def setup(self, harness, location="millhaven_inn"):
        await self.start(harness, "rest", stage=None)
        self.sd.location_id = location
        self.anchor = "millhaven" if location == "millhaven_inn" else "accord_market_square"
        self.sd.world_time = "morning"
        self.ids = [self.player + suffix for suffix in ("", "_guest", "_remote", "_offline", "_hp")]
        for i, pid in enumerate(self.ids):
            if i:
                await seed_player(self.pool, player_id=pid, location_id=location)
                self.sd.party.members.append(SessionData(player_id=pid, location_id=location).party.primary)
            patch = {
                "location_id": "millhaven" if i == 2 else location,
                "hp": {"current": 5 + i, "max": 30 + i},
                "last_rested_settlement_id": "old_anchor",
                "resonance": {"current": 7, "flickering_bonus": 1},
            }
            if i == 4:
                patch["stamina"] = {"current": 7, "max": 14}
            else:
                patch.update(stamina={"current": 3 + i, "max": 10 + i}, focus={"current": 8 if i else 0, "max": 11})
            await self.pool.execute(
                "UPDATE players SET data=(data-'stamina'-'focus'-'player_id') || $2::jsonb WHERE player_id=$1",
                pid,
                json.dumps(patch),
            )
            self.sd.member_state(pid).resonance.current = 7
            self.sd.member_state(pid).resonance.flickering_bonus = 1
        room = cast(MagicMock, self.sd.room)
        room.remote_participants = {pid: SimpleNamespace(identity=pid) for i, pid in enumerate(self.ids) if i != 3}
        lifecycle = PartyLifecycle(room, self.sd, queries=None, resonance_mod=None, concentration_mod=None)
        self.validator = lifecycle.require_authorized
        harness.stack.callback(lambda: harness.run_sync(lifecycle.aclose()))
        self.sd.multiplayer_owner = GameplayInputOwner(lifecycle, MagicMock(), MagicMock())
        # Joins hydrate in background tasks; settle them (raising on failure) before the walk records events.
        for pid in room.remote_participants:
            await lifecycle.authorize(pid)
        self.before = await self.rows()
        self.events.clear()
        return self

    async def solo(self):
        self.ids = self.ids[:1]
        self.sd.party.members = self.sd.party.members[:1]
        self.sd.multiplayer_owner = None
        self.validator = lambda *_: None
        self.before = await self.rows()

    async def row(self, pid) -> dict:
        row = await db_queries.get_player(pid)
        assert row is not None
        return row

    async def rows(self):
        return {pid: await self.row(pid) for pid in self.ids}

    async def publish(self, raw, **kwargs):
        event = json.loads(raw)
        if event["type"] == E.SESSION_INIT and not self.resting:
            return  # join and reconnect also send session_init (participant_lifecycle); only rest's are walked
        if event["type"] == E.SESSION_INIT:
            character = event["character"]
            persisted = await self.row(character["player_id"])
            if character["player_id"] == self.player:
                persisted["hp"]["max"] += self.primary_hp_bonus
            assert {k: v for k, v in character.items() if k != "player_id"} == persisted, (character, persisted)
            for i, pid in enumerate(self.ids):
                if i not in (0, 1, 4):
                    continue
                assert (await self.row(pid))["resonance"]["current"] == 0
            assert event["world_state"]["time"] == "morning"
            assert "spells" in event and "companion" in event
        self.events.append(event)

    async def command(self, kind):
        self.model.commands.append(("rest", {"rest_type": kind}))
        self.resting = True
        try:
            with self.sd._bind_authenticated_actor(self.player, 1, self.validator):
                await self.session.run(user_input="Rest now.")
        finally:
            self.resting = False
        return list(self.model.receipts.values())[-1]

    async def restored(self, kind, receipt=None):
        receipt = receipt or await self.command(kind)
        assert receipt.name == "rest" and not receipt.is_error, receipt.output
        assert json.loads(receipt.output)["rested"]
        rows = await self.rows()
        for i, pid in enumerate(self.ids):
            expected = copy.deepcopy(self.before[pid])
            if i in (0, 1, 4):
                stamina = expected.get("stamina", {})
                focus = expected.get("focus", {})
                args = (stamina.get("current"), stamina.get("max"), focus.get("current"), focus.get("max"))
                s, f = apply_short_rest(*args)
                if kind == "long":
                    s, f, _ = apply_long_rest(*args, 5 + i, 30 + i)
                for key, current in (("stamina", s), ("focus", f)):
                    if key in expected:
                        expected[key]["current"] = current
                if kind == "long":
                    expected["hp"]["current"] = 30 + i
                    expected["last_rested_settlement_id"] = self.anchor
                    expected["travel_hours_since_rest"] = 0
                expected["resonance"]["current"] = 0
                assert self.sd.member_state(pid).resonance.current == 0
            else:
                assert self.sd.member_state(pid).resonance.current == 7
            assert rows[pid] == expected
            assert self.sd.member_state(pid).resonance.flickering_bonus == 1
        snapshots = [e["character"]["player_id"] for e in self.events if e["type"] == E.SESSION_INIT]
        assert sorted(snapshots) == sorted(pid for i, pid in enumerate(self.ids) if i in (0, 1, 4))
        assert sorted(e["caster_id"] for e in self.events if e["type"] == E.RESONANCE_CHANGED) == sorted(snapshots)
        assert all(e["state"] == "stable" for e in self.events if e["type"] == E.RESONANCE_CHANGED)
        if kind == "short":
            self.before = rows
            self.events.clear()
            await self.restored("long")

    async def obstruct(self, harness, obstacle):
        if obstacle == "combat":
            self.sd.combat_state = CombatState("rest_combat", [], [])
        elif obstacle == "remote_actor":
            await self.pool.execute(
                "UPDATE players SET data=jsonb_set(data,'{location_id}',$2::jsonb) WHERE player_id=$1",
                self.player,
                json.dumps("millhaven"),
            )
        elif obstacle == "street":
            self.sd.location_id = "millhaven"
        elif obstacle in ("malformed_pool", "missing_hp"):
            patch = {"focus": {"current": True, "max": 11}} if obstacle == "malformed_pool" else {"hp": None}
            await self.pool.execute(
                "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", self.ids[1], json.dumps(patch)
            )
        else:
            room = copy.deepcopy(await db_content_queries.get_location("millhaven_inn"))
            assert room is not None
            room["id"] = self.player + "_room"
            if obstacle in ("danger", "null_danger"):
                room["danger_level"] = 1 if obstacle == "danger" else None
            elif obstacle == "tier":
                del room["settlement_tier"]
            else:
                room["exits"] = (
                    {"away": {"destination": "accord_market_square"}, "road": {"destination": "greyvale_south_road"}}
                    if obstacle == "no_parent"
                    else {"a": {"destination": "millhaven"}, "b": {"destination": "millhaven_inn"}}
                )
            await self.private_room(harness, room)
        self.before = await self.rows()
        receipts = []
        for kind in ("short", "long") if obstacle not in ("no_parent", "two_parents") else ("long",):
            receipt = await self.command(kind)
            receipts.append(receipt)
            reason = {
                "combat": "combat",
                "remote_actor": "no longer",
                "null_danger": "dangerous",
                "street": "no place",
                "danger": "dangerous",
                "tier": "settlement",
                "no_parent": "error",
                "two_parents": "error",
                "malformed_pool": "error",
                "missing_hp": "error",
            }[obstacle]
            assert reason in receipt.output.lower(), receipt.output
            assert await self.rows() == self.before
            assert not self.events
            assert all(self.sd.member_state(pid).resonance.current == 7 for pid in self.ids)
        return receipts

    async def private_room(self, harness, room):
        room["id"] = self.player + "_room"
        await self.pool.execute("INSERT INTO locations(id,data) VALUES($1,$2::jsonb)", room["id"], json.dumps(room))
        self.sd.location_id = room["id"]
        await self.pool.execute(
            "UPDATE players SET data=jsonb_set(data,'{location_id}',$2::jsonb) WHERE player_id=ANY($1)",
            [pid for i, pid in enumerate(self.ids) if i != 2],
            json.dumps(room["id"]),
        )

        async def cleanup():
            await self.pool.execute("DELETE FROM locations WHERE id=$1", room["id"])
            await (await db.get_redis()).delete("location:" + room["id"])

        harness.stack.callback(lambda: harness.run_sync(cleanup()))
        self.before = await self.rows()

    async def duplicate_exit(self, harness):
        room = copy.deepcopy(await db_content_queries.get_location(self.sd.location_id))
        assert room is not None
        room["exits"]["another_door"] = copy.deepcopy(next(iter(room["exits"].values())))
        await self.private_room(harness, room)


@given(parsers.parse("a wounded resting party at {location}"))
def resting_party(harness, location):
    harness.state["rest"] = harness.run_sync(RestWalk().setup(harness, location))


@when(parsers.parse("the host requests a {kind} rest"))
def rest_request(harness, kind):
    harness.state["rest_receipt"] = harness.run_sync(harness.state["rest"].command(kind))


@then(parsers.parse("the resting party and identified client snapshots agree for {kind}"))
def restored_party(harness, kind):
    harness.run_sync(harness.state["rest"].restored(kind, harness.state["rest_receipt"]))


@when(parsers.parse("the host requests rest with {obstacle}"))
def blocked_rest(harness, obstacle):
    harness.state["refusals"] = harness.run_sync(harness.state["rest"].obstruct(harness, obstacle))


@then("rest refuses without writes or client updates")
def refused_rest(harness):
    assert harness.state["refusals"]
    assert all(receipt.is_error for receipt in harness.state["refusals"])


@given("the resting player is alone")
def solo_rest(harness):
    harness.run_sync(harness.state["rest"].solo())


@given("two doors connect the inn to the same settlement")
def duplicate_rest_exit(harness):
    harness.run_sync(harness.state["rest"].duplicate_exit(harness))
