"""Equipped artificer strikes against a catalog Hollowed Knight."""

import json
from collections.abc import AsyncIterator
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.seeds import seed_player_with_pools
from acceptance.test_architect_entomb import favor
from acceptance.test_architect_fight import pos
from acceptance.test_opportunity_strike import MOVER, participant, reconnect
from acceptance.test_weapon_proficiency_equip import declare_weapon

import db_queries
from activate_tools import activate
from combat_spatial import require_spatial
from creation_classes import CLASSES
from inventory_tools import transact
from rest_tools import rest
from rules_engine import attribute_modifier, proficiency_bonus

INFUSE = "artificer_infuse_item"
SHORTSWORD = "shortsword_basic"
CLUB = "club_wooden"
HANDAXE = "handaxe_common"
DAGGER = "dagger_balanced"
STARTER = "warhammer_common"
ASHMARK = "blade_of_the_ashmark"
INN = "millhaven_inn"


class InfusionWalk(MawlingHarness):
    async def setup(self, level: int, *, starter: bool, focus: int) -> None:
        await self.prepare((level, level), companion=None, location=INN, tools=(activate, transact, rest))
        self.actor = self.players[0]
        await seed_player_with_pools(self.pool, player_id=self.actor, class_="artificer", focus_current=focus)
        row = await self.row()
        row.update(level=level, location_id=INN, gold=0, focus={"current": focus, "max": 12})
        row["equipment"] = CLASSES["artificer"].starting_equipment if starter else {}
        await self.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", self.actor, json.dumps(row))
        self.encounter_id = f"knight_infusion_{uuid4().hex}"
        template = {
            "id": self.encounter_id,
            "name": "Knight patrol",
            "description": "A plated boot scrapes the road.",
            "difficulty": "hard",
            "recommended_party_level": level,
            "enemies": [
                {"id": MOVER, "creature_id": "hollow_knight", "role": "standard"},
                {"id": "lookout", "creature_id": "bandit", "role": "standard"},
            ],
            "scene_placement": {
                "party_start": pos(0),
                "companion_start": pos(0),
                "actors": {MOVER: pos(3), "lookout": pos(-30)},
                "zones": {},
                "locations": {},
            },
        }
        await self.pool.execute(
            "INSERT INTO encounter_templates (id, data) VALUES ($1,$2::jsonb)", self.encounter_id, json.dumps(template)
        )
        self.owns_template = True

    async def row(self) -> dict:
        row = await db_queries.get_player(self.actor)
        assert row is not None
        return row

    async def equip(self, item: str, *, acquire: bool = False) -> None:
        if acquire:
            assert (await self.command("transact", {"action": "exchange", "item_id": item, "delta": 1}))[
                "action"
            ] == "added"
        assert (await self.command("transact", {"action": "equip", "item_id": item, "delta": 0}))[
            "action"
        ] == "equipped"

    async def weapon(self) -> dict:
        return (await self.row())["equipment"]["main_hand"]

    async def infusions(self) -> dict:
        return (await self.row()).get("weapon_infusions", {})

    async def activate_infusion(self, *, error: bool = False) -> dict | str:
        return await self.command("activate", {"id": INFUSE}, error=error)

    async def infuse(self, item: str, bonus: int, *, replaced: str | None = None) -> None:
        before = (await self.row())["focus"]["current"]
        receipt = await self.activate_infusion()
        assert isinstance(receipt, dict)
        expected = {
            "item_id": item,
            "name": (await self.weapon())["name"],
            "attack_bonus": bonus,
            "damage_bonus": bonus,
            "magical": True,
            "expiry": "next_long_rest",
            "replaced_item_id": replaced,
        }
        assert receipt["infusion"] == expected, receipt["infusion"]
        assert (await self.row())["focus"]["current"] == before - 2
        assert set((await self.infusions())[item]) == {"order"}

    async def lookup(self) -> dict:
        result = await self.command("query_info", {"kind": "abilities"})
        (ability,) = [row for row in result["abilities"] if row["id"] == INFUSE]
        assert ability["combat"] is False
        assert "outside combat" in ability["effect"].lower()
        return ability["infusion"]

    async def enter(self) -> None:
        await self.command("enter_mode", {"mode": "combat", "encounter_id": self.encounter_id})
        state = await self.reload()
        require_spatial(state)["positions"].update({self.actor: pos(0), self.players[1]: pos(25)})
        await self.persist()

    async def strike(self, bonus: int, *, mode: str = "ordinary", finish: bool = False, critical: bool = False) -> None:
        row = await self.row()
        weapon = row["equipment"]["main_hand"]
        if mode == "held":
            await favor(self)
        await self.enter()
        if mode == "reloaded":
            await reconnect(self)
        hp = participant(await self.reload(), MOVER).hp_current
        await declare_weapon(self, MOVER, weapon["name"])
        disadvantaged = weapon.get("id") == SHORTSWORD
        face = 20 if critical else 18
        faces = (face + 1, face) if disadvantaged and not critical else (face,) * (1 + disadvantaged)
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in faces]) as rolls,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
        ):
            if mode == "held":
                offer = (await self.command("resolve_phase", {}))["fate_offer"]
                assert (offer["roll_kind"], offer["roller_id"]) == ("attack", self.actor)
                damage.assert_not_called()
                saved = await self.reload()
                assert participant(saved, MOVER).hp_current == hp
                assert saved.ally_continuation is not None
                assert saved.ally_continuation["attack"]["prepared"]
                await reconnect(self)
            packets = await self.drain()
            assert rolls.call_count == len(faces)
            assert damage.call_count == 1 + critical
        (attack,) = [packet for packet in packets if packet.get("actor_id") == self.actor and "hit" in packet]
        assert attack["hit"] and attack["roll"] == face and attack["critical"] is critical
        assert attack.get("attack_disadvantage_source") == ("weapon_proficiency" if disadvantaged else None)
        attributes = row["attributes"]
        score = attributes["strength"]
        if "finesse" in weapon["properties"]:
            score = max(score, attributes["dexterity"])
        modifier = attribute_modifier(score)
        assert attack["attack_total"] == face + modifier + proficiency_bonus(row["level"]) + bonus
        raw_damage = 4 * (1 + critical) + modifier + bonus
        expected = raw_damage if bonus else raw_damage // 2
        assert attack["damage"] == expected
        assert participant(await self.reload(), MOVER).hp_current == hp - expected
        assert (await self.row())["focus"] == row["focus"]
        if finish:
            await self.command("end_combat", {"outcome": "fled"})


@pytest.fixture
async def walk(reset_db_pool: str, request: pytest.FixtureRequest) -> AsyncIterator[InfusionWalk]:
    harness = InfusionWalk()
    level, starter, focus = getattr(request, "param", (4, False, 12))
    try:
        await harness.setup(level, starter=starter, focus=focus)
        yield harness
    finally:
        await harness.close()
