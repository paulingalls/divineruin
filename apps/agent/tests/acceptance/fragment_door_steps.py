"""Fragment passage through the authored seal, including the production warm rebuild."""

import os
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from acceptance.first_blood_walk import FirstBloodWalk
from acceptance.greyvale_arc_walk_harness import ArcWalk
from acceptance.seeds import seed_player
from pytest_bdd import given, parsers, then, when

import db
import db_mutations
import db_mutations_concentration
import db_mutations_resonance
import db_queries
import event_types as E
from background_process import BackgroundProcess
from event_bus import GameEvent
from exploration_agent import ExplorationAgent
from participant_lifecycle import PartyLifecycle
from party_state import PartyState

ENTRANCE = "greyvale_ruins_entrance"
INNER = "greyvale_ruins_inner"
FRAGMENT = "greyvale_veil_fragment"


class FragmentDoorWalk(FirstBloodWalk):
    async def start(self, harness, holding):
        harness.stack.enter_context(patch.object(ExplorationAgent, "_enter", new=AsyncMock()))
        await ArcWalk.start(
            self, harness, "move_player", stage=5 if holding == "neither" else None, agent=ExplorationAgent()
        )
        await (await db.get_redis()).delete(os.environ.get("CONTENT_CACHE_PREFIX", "") + "location:" + ENTRANCE)
        self.sd.location_id = ENTRANCE
        await db_mutations.update_player_location(self.player, ENTRANCE)
        self.guest = self.player + "_guest"
        await seed_player(self.pool, player_id=self.guest, class_="warrior", location_id=ENTRANCE)
        if holding.startswith("guest"):
            self.sd.party.members.append(PartyState.solo(self.guest).primary)
        owner = self.guest if holding.startswith(("guest", "nonmember")) else self.player
        if holding not in {"neither", "seal"}:
            await db_mutations.add_inventory_item(owner, FRAGMENT, 1, tainted=holding == "tainted")
            if holding == "guest_zero":
                await self.pool.execute(
                    "UPDATE player_inventory SET data=jsonb_set(data, '{quantity}', '0') "
                    "WHERE player_id=$1 AND item_id=$2",
                    owner,
                    FRAGMENT,
                )
        if holding in {"neither", "guest_zero", "nonmember"}:
            await db_mutations.add_inventory_item(self.player, "aldric_strange_stone", 1, tainted=False)
        if holding == "seal":
            await db_mutations.set_player_flag(self.player, "veythar_seal_mark.discovered", True)
        if holding not in {"neither", "seal"}:
            held = [r for r in await db_queries.get_player_inventory(owner) if r["id"] == FRAGMENT]
            assert len(held) == 1 and held[0]["slot_info"]["quantity"] == (0 if holding == "guest_zero" else 1)
        assert self.sd.room is not None
        self.lifecycle = PartyLifecycle(
            self.sd.room,
            self.sd,
            queries=db_queries,
            resonance_mod=db_mutations_resonance,
            concentration_mod=db_mutations_concentration,
        )
        self.sd.multiplayer_owner = cast(Any, SimpleNamespace(lifecycle=self.lifecycle))
        for pid in self.sd.party.member_ids:
            self.lifecycle._on_connected(cast(Any, SimpleNamespace(identity=pid)))
        harness.stack.callback(lambda: harness.run_sync(self.lifecycle.aclose()))
        if holding == "guest_disconnected":
            self.lifecycle._on_disconnected(cast(Any, SimpleNamespace(identity=self.guest)))
            assert not self.lifecycle.is_live(self.guest) and self.sd.party.contains(self.guest)
        self.holding = holding
        self.marker_before = await db_queries.get_player_quest(self.player, "greyvale_anomaly")
        self.before = await self.inventory()
        self.bg = BackgroundProcess(self.session, self.sd)
        return self

    async def inventory(self):
        return {
            pid: [(r["id"], r["slot_info"]) for r in await db_queries.get_player_inventory(pid)]
            for pid in (self.player, self.guest)
        }

    async def attempt(self):
        await self.bg._process_events([GameEvent(E.QUEST_UPDATED, {})], timed_out=False)
        self.warm = self.bg._last_warm_layer
        instructions = self.session.current_agent.instructions
        assert isinstance(instructions, str) and self.warm in instructions
        self.events.clear()
        self.result = await self.command("move_player", {"destination_id": INNER})

    async def observed(self, allowed):
        assert bool(self.result.get("moved")) == allowed, self.result
        assert bool(self.result.get("blocked")) != allowed, self.result
        assert self.sd.location_id == (INNER if allowed else ENTRANCE)
        for pid in self.sd.party.member_ids:
            row = await db_queries.get_player(pid)
            assert row is not None
            assert row["location_id"] == self.sd.location_id
        changed = [e for e in self.events if e["type"] == E.LOCATION_CHANGED]
        assert bool(changed) == allowed
        if allowed:
            assert self.result["location"]["id"] == INNER
            assert all(e["new_location"] == INNER for e in changed)
            assert "deeper → " + INNER in next(s for s in self.warm.splitlines() if "  go:" in s)
        else:
            assert self.result["destination"] == INNER
            assert "deeper (locked)" in self.warm
            assert not any("deeper" in s for s in self.warm.splitlines() if "  go:" in s)
        for raw in ("item:" + FRAGMENT, "skill_check:arcana:14", "veythar_seal_mark.discovered"):
            assert raw not in self.warm
            assert raw not in self.result.get("message", "")
        assert await self.inventory() == self.before
        assert await db_queries.get_player_quest(self.player, "greyvale_anomaly") == self.marker_before
        assert await db_queries.get_inventory_item(self.player, "veythar_sealed_artifact") is None
        assert not [e for e in self.events if e["type"] in {E.QUEST_UPDATED, E.INVENTORY_UPDATED}]
        if self.holding == "guest_disconnected" and not allowed:
            self.lifecycle._on_connected(cast(Any, SimpleNamespace(identity=self.guest)))
            self.holding = "guest"
            await self.attempt()
            await self.observed(True)


@given(parsers.parse("a sealed door party with {holding}"))
def fragment_party(harness, holding):
    harness.state["door"] = harness.run_sync(FragmentDoorWalk().start(harness, holding))


@when("the host asks to pass the inner seal")
def fragment_attempt(harness):
    harness.run_sync(harness.state["door"].attempt())


@then(parsers.parse("the seal passage is {outcome}"))
def fragment_observed(harness, outcome):
    harness.run_sync(harness.state["door"].observed(outcome == "allowed"))
