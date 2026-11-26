"""Registered Quick Fingers fights with deterministic pockets and room events."""

import json
from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_martial_core_kit import weapon_attack
from sample_fixtures import published_payloads
from weapon_fixtures import DAGGER, SHORTBOW

import ability_persistence
import combat_spatial
import db_queries
import event_types as E

ABILITY = "rogue_quick_fingers"
POCKET = [
    {"item_id": "wolf_fangs", "quantity": 1, "tainted": False},
    {"item_id": "rend_shard", "quantity": 3, "tainted": True},
]


class FingersFight(MawlingHarness):
    actor: str
    foe: str
    weapon: str

    async def set_player(self, **data) -> None:
        await self.pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", self.actor, json.dumps(data)
        )

    async def inventory(self) -> dict[tuple[str, bool], int]:
        return {
            (row["id"], row["tainted"]): row["slot_info"]["quantity"]
            for row in await db_queries.get_player_inventory(self.actor)
        }

    async def resources(self) -> tuple[int, int]:
        row = await db_queries.get_player(self.actor)
        assert row is not None
        return row["stamina"]["current"], row["focus"]["current"]

    def inventory_events(self) -> list[dict]:
        return [
            event
            for event in published_payloads(self.sd.room)
            if event["type"] in (E.ITEM_ACQUIRED, E.INVENTORY_UPDATED)
        ]

    async def target(self):
        target = (await self.reload()).get_participant(self.foe)
        assert target is not None
        return target

    def attack(self, mode: str, item: str = "", *, actor: str | None = None, target: str | None = None) -> dict:
        return {
            **weapon_attack(actor or self.actor, target or self.foe, "quick_fingers", weapon=self.weapon),
            "quick_fingers_mode": mode,
            "quick_fingers_item": item,
        }

    async def declare(self, *declarations: dict, error: bool = False):
        return await self.command("declare_phase", {"declarations": list(declarations)}, error=error)

    async def swing(self, *faces: int) -> dict:
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in faces]) as d20,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            packets = await self.drain()
        assert d20.call_count == len(faces)
        return next(packet for packet in packets if packet["actor_id"] == self.actor)


@pytest.fixture
async def fingers(reset_db_pool, request: pytest.FixtureRequest) -> AsyncIterator[FingersFight]:
    settings = getattr(request, "param", {})
    h = FingersFight()
    weapon = SHORTBOW if settings.get("ranged") else DAGGER
    try:
        await h.prepare((4,) * settings.get("players", 1), companion=None)
        h.actor = h.players[0]
        h.weapon = weapon["name"]
        for player in h.players:
            await h.pool.execute(
                "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
                player,
                json.dumps(
                    {
                        "class": "rogue",
                        "attributes": {
                            attribute: 10
                            for attribute in (
                                "strength",
                                "dexterity",
                                "constitution",
                                "intelligence",
                                "wisdom",
                                "charisma",
                            )
                        },
                        "equipment": {"main_hand": weapon},
                    }
                ),
            )
            if settings.get("owned", True):
                await ability_persistence.set_elective_equipped(player, ABILITY, equipped=True)
        entry = await h.command("enter_mode", {"mode": "combat", "encounter_id": h.encounter_id})
        h.roster = entry["participants"]
        h.enemies = [row["id"] for row in h.roster if row["type"] == "enemy"]
        state = await h.reload()
        h.foe = h.enemies[0]
        target = state.get_participant(h.foe)
        assert target is not None
        target.hp_current = target.hp_max = 100
        target.ac = 10
        target.attributes["wisdom"] = 14
        target.carried_items = [] if settings.get("empty") else [dict(drop) for drop in POCKET]
        state.initiative_order = [*h.players, *h.enemies]
        for index, pid in enumerate(state.initiative_order):
            participant = state.get_participant(pid)
            assert participant is not None
            participant.initiative = 25 - index
        origin = combat_spatial.position(combat_spatial.require_spatial(state), h.actor)
        for pid in h.players[1:]:
            combat_spatial.place(state, pid, origin)
        combat_spatial.place(state, h.foe, {**origin, "x": origin["x"] + settings.get("distance", 5)})
        await h.persist()
        yield h
    finally:
        await h.close()
