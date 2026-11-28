import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import pos
from acceptance.test_opportunity_strike import participant
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_weapon_proficiency_equip import declare_weapon

import db_queries
from inventory_tools import transact

QUALITY = "quality_longsword"
BASE = "longsword_guild"
FOE = "lookout"


async def swing(item_id: str, face: int, dice: int, bonus: int) -> int:
    fight = MawlingHarness()
    try:
        await fight.prepare(companion=None, tools=(transact,))
        grant = await fight.command("transact", {"action": "exchange", "item_id": item_id, "delta": 1})
        assert grant["action"] == "added"
        equip = await fight.command("transact", {"action": "equip", "item_id": item_id, "delta": 0})
        assert equip["action"] == "equipped"
        actor = fight.players[0]
        row = await db_queries.get_player(actor)
        assert row is not None
        weapon = row["equipment"]["main_hand"]
        assert weapon["id"] == item_id
        modifier = (row["attributes"]["strength"] - 10) // 2

        fight.encounter_id = f"masterwork_{uuid4().hex}"
        fight.owns_template = True
        template = {
            "id": fight.encounter_id,
            "name": "Road lookout",
            "description": "Boots scrape against the road.",
            "difficulty": "easy",
            "recommended_party_level": 3,
            "enemies": [{"id": FOE, "creature_id": "bandit", "role": "standard"}],
            "scene_placement": {
                "party_start": pos(0),
                "companion_start": pos(0),
                "actors": {FOE: pos(3)},
                "zones": {},
                "locations": {},
            },
        }
        await fight.pool.execute(
            "INSERT INTO encounter_templates (id, data) VALUES ($1,$2::jsonb)", fight.encounter_id, json.dumps(template)
        )
        await fight.command("enter_mode", {"mode": "combat", "encounter_id": fight.encounter_id})
        before = participant(await fight.reload(), FOE).hp_current
        await declare_weapon(fight, FOE, weapon["name"])
        with (
            patch("check_resolution.dice_roll", return_value=_d20(face)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            packets = await fight.drain()
        (attack,) = [packet for packet in packets if packet.get("actor_id") == actor and "hit" in packet]
        expected_damage = 4 * dice + modifier + bonus if dice else 0
        assert participant(await fight.reload(), FOE).hp_current == before - expected_damage
        assert attack["damage"] == expected_damage
        assert attack["hit"] is bool(dice)
        assert attack["critical"] is (face == 20)
        assert attack["item_damage_bonus"] == bonus
        return attack["attack_total"]
    finally:
        await fight.close()


@pytest.mark.parametrize(("face", "dice"), [(18, 1), (20, 2), (1, 0)], ids=["hit", "critical", "miss"])
async def test_masterwork_weapon_damage(reset_db_pool: str, face: int, dice: int) -> None:
    quality_total = await swing(QUALITY, face, dice, int(bool(dice)))
    if dice:
        assert await swing(BASE, face, dice, 0) == quality_total
