"""Private catalog encounters for the registered Turn Undead/Hollow walk."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from acceptance.mawling_harness import MawlingHarness
from acceptance.seeds import seed_player_with_pools
from sample_fixtures import published_payloads

import db_queries
from activate_tools import activate
from combat_agent import CombatAgent
from combat_participant import CombatParticipant
from encounter_actions import action_kind

TURN = "divine_turn_undead_hollow"


def pos(x: float) -> dict:
    return {"x": x, "y": 0, "z": 0}


class TurnFight(MawlingHarness):
    async def ready(
        self,
        level: int,
        *,
        weapon: dict | None = None,
        archetype: str = "cleric",
        patron: str | None = None,
        known_spells: tuple[str, ...] = (TURN,),
    ) -> None:
        await self.prepare(levels=(level,), companion=None, tools=(activate,))
        self.caster = self.players[0]
        await seed_player_with_pools(self.pool, player_id=self.caster, class_=archetype, known_spells=known_spells)
        row = await self.player()
        row.update(level=level, hp={"current": 100, "max": 100}, location_id=self.sd.location_id)
        row["attributes"]["wisdom"] = 18
        if patron is not None:
            row["divine_favor"] = {"patron": patron, "level": 40, "max": 100}
        if weapon is not None:
            row["equipment"] = {**row.get("equipment", {}), "main_hand": weapon}
        await self.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", self.caster, json.dumps(row))

    async def player(self) -> dict:
        row = await db_queries.get_player(self.caster)
        assert row is not None
        return row

    async def enter(
        self,
        creatures: dict[str, tuple[str, int]],
        *,
        level: int = 4,
        weapon: dict | None = None,
        archetype: str = "cleric",
        patron: str | None = None,
        known_spells: tuple[str, ...] = (TURN,),
    ) -> None:
        await self.ready(level, weapon=weapon, archetype=archetype, patron=patron, known_spells=known_spells)
        prefix = uuid4().hex
        self.undead_id = f"turn_undead_{prefix}"
        fixtures = json.loads(
            (Path(__file__).resolve().parents[4] / "packages/shared/fixtures/creature_blocks.json").read_text()
        )
        undead = next(case["block"] for case in fixtures["valid"] if case["name"] == "synthetic_undead")
        undead.update(id=self.undead_id, hp=30)
        await self.pool.execute(
            "INSERT INTO creatures (id,data) VALUES ($1,$2::jsonb)", self.undead_id, json.dumps(undead)
        )
        self.encounter_id = f"turn_{prefix}"
        await self.pool.execute(
            "INSERT INTO encounter_templates (id,data) VALUES ($1,$2::jsonb)",
            self.encounter_id,
            json.dumps(
                {
                    "id": self.encounter_id,
                    "name": "Turning Ground",
                    "difficulty": "easy",
                    "recommended_party_level": level,
                    "enemies": [
                        {
                            "id": actor,
                            "creature_id": self.undead_id if creature == "undead" else creature,
                            "role": "standard",
                        }
                        for actor, (creature, _) in creatures.items()
                    ],
                    "scene_placement": {
                        "party_start": pos(0),
                        "companion_start": pos(-5),
                        "actors": {actor: pos(x) for actor, (_, x) in creatures.items()},
                        "locations": {},
                        "zones": {},
                    },
                }
            ),
        )
        self.owns_template = True
        result = await self.command("enter_mode", {"mode": "combat", "encounter_id": self.encounter_id})
        assert isinstance(self.session.current_agent, CombatAgent)
        self.roster = result["participants"]
        self.enemies = list(creatures)
        state = await self.reload()
        caster = self.actor(self.caster)
        assert caster.level == level and caster.attributes["wisdom"] == 18
        caster.initiative = 40
        state.initiative_order = [self.caster, *creatures]
        for index, (actor, (creature, _)) in enumerate(creatures.items()):
            target = self.actor(actor)
            target.initiative = 20 - index
            if creature == "undead":
                assert (target.category, target.creature_id) == ("undead", self.undead_id)
                assert target.xp_value == undead["xp_reward"] and target.action_pool
        await self.persist()

    def actor(self, actor_id: str) -> CombatParticipant:
        state = self.sd.combat_state
        assert state is not None
        actor = state.get_participant(actor_id)
        assert actor is not None
        return actor

    def attack(self, actor_id: str, *, ranged: bool = False) -> dict:
        actor = self.actor(actor_id)
        action = next(a for a in actor.action_pool if action_kind(a) == "attack" and (a["type"] == "ranged") == ranged)
        return {
            "kind": "attack",
            "actor_id": actor_id,
            "action": action["name"],
            "target_id": self.caster,
            "held_item_id": "",
            "rider": "",
            "quick_fingers_mode": "",
            "quick_fingers_item": "",
            "reshape": [],
        }

    async def declare_turn(self, *declarations: dict, cast: bool = False) -> None:
        roster = {d["actor_id"]: d for d in declarations}
        if cast:
            roster[self.caster] = {
                "kind": "ability",
                "actor_id": self.caster,
                "action": TURN,
                "targets": [],
                "argument_type": "",
            }
        for actor_id in (self.caster, *self.enemies):
            if not self.actor(actor_id).is_fallen:
                roster.setdefault(actor_id, {"kind": "defend", "actor_id": actor_id, "reshape": []})
        await self.command("declare_phase", {"declarations": list(roster.values())})

    async def phase(self, *declarations: dict, cast: bool = False) -> list[dict]:
        await self.declare_turn(*declarations, cast=cast)
        return await self.drain()

    def cast(self, packets: list[dict]) -> dict:
        return next(p["cast"] for p in packets if p.get("action") == TURN)

    def events(self) -> list[dict]:
        return published_payloads(self.sd.room)


@pytest.fixture
async def fight(reset_db_pool: str, mock_combat_agent_factory: None) -> AsyncIterator[TurnFight]:
    fight = TurnFight()
    try:
        yield fight
    finally:
        try:
            if hasattr(fight, "session"):
                await fight.close()
        finally:
            if hasattr(fight, "undead_id"):
                await fight.pool.execute("DELETE FROM creatures WHERE id=$1", fight.undead_id)
