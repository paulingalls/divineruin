"""Skill-gated rewards through persisted CombatAgent victory commands."""

import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from acceptance.mawling_harness import MawlingHarness
from acceptance.seeds import seed_player_with_pools
from acceptance.voice_condition_harness import ScenarioModel
from livekit.agents import Agent, AgentSession
from sample_fixtures import make_mock_room, published_payloads

import db
import db_queries
import event_types as E
from caster_state import ConcentrationState, ResonanceTrack
from combat_agent import CombatAgent
from combat_end import _end_combat_db
from combat_spatial import distance
from mode_tools import enter_mode
from party_state import PartyMember
from session_data import SessionData


class LootHarness(MawlingHarness):
    async def start_loot(self, creature, tiers, count):
        self.pool = await db.get_pool()
        self.encounter_id = f"loot_{uuid4().hex}"
        template = {
            "id": self.encounter_id,
            "name": "Harvest test",
            "difficulty": "easy",
            "enemies": [
                {
                    "id": f"foe_{i}",
                    "creature_id": creature[i] if isinstance(creature, list) else creature,
                    "role": "standard",
                }
                for i in range(count)
            ],
            "recommended_party_level": 2,
            "scene_placement": {
                "party_start": {"x": 0, "y": 0, "z": 0},
                "companion_start": {"x": 0, "y": 5, "z": 0},
                "actors": {f"foe_{i}": {"x": 5, "y": i * 5, "z": 0} for i in range(count)},
                "locations": {},
                "zones": {},
            },
        }
        await self.pool.execute(
            "INSERT INTO encounter_templates (id, data) VALUES ($1,$2::jsonb)", self.encounter_id, json.dumps(template)
        )
        prefix = uuid4().hex
        self.players = [f"loot_{prefix}_{i}" for i in range(len(tiers))]
        for pid, skills in zip(self.players, tiers, strict=True):
            await seed_player_with_pools(self.pool, player_id=pid, class_="warrior")
            row = await db_queries.get_player(pid)
            assert row is not None
            row.update(
                gold=0,
                proficiencies=[skill for skill, tier in skills.items() if tier == "trained"],
                equipment={"main_hand": {"name": "Longsword", "damage": "1d8", "damage_type": "slashing"}},
                hp={"current": 100, "max": 100},
            )
            await self.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(row))
            for skill, tier in skills.items():
                if tier != "trained":
                    await self.pool.execute(
                        "INSERT INTO skill_advancement (player_id, skill_id, tier) VALUES ($1,$2,$3)", pid, skill, tier
                    )
        self.sd = SessionData(player_id=self.players[0], location_id="accord_guild_hall", room=make_mock_room())
        for pid in self.players[1:]:
            self.sd.party.members.append(PartyMember(pid, ResonanceTrack(), ConcentrationState()))
        self.model = ScenarioModel([])
        self.session = AgentSession(llm=self.model, max_tool_steps=5, userdata=self.sd)
        await self.session.start(Agent(instructions="Execute the command.", tools=[enter_mode]))
        result = await self.command("enter_mode", {"mode": "combat", "encounter_id": self.encounter_id})
        assert isinstance(self.session.current_agent, CombatAgent)
        self.roster = result["participants"]
        self.enemies = [p["id"] for p in self.roster if p["type"] == "enemy"]
        await self.persist()

    async def victory(self, rng):
        async def end(*args, **kwargs):
            return await _end_combat_db(*args, **kwargs, rng=rng)

        state = self.sd.combat_state
        assert state is not None
        combat_id = state.combat_id
        with (
            patch("combat_wrap._end_combat_db", side_effect=end),
            patch("combat_end._build_handoff_agent", side_effect=lambda *_: Agent(instructions="Combat complete.")),
            patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=19)),
            patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=999)),
        ):
            for enemy in self.enemies:
                state = self.sd.combat_state
                assert state is not None
                assert state.spatial is not None
                destination = state.spatial["positions"][enemy]
                if distance(state.spatial["positions"][self.players[0]], destination) > 5:
                    await self.command(
                        "declare_phase",
                        {
                            "declarations": [
                                {"kind": "move", "actor_id": self.players[0], "destination": destination},
                                *[
                                    {"kind": "defend", "actor_id": p.id}
                                    for p in state.participants
                                    if p.id != self.players[0] and not p.is_fallen
                                ],
                            ]
                        },
                    )
                    packets = await self.drain()
                    assert any(p.get("moved_ft", 0) > 0 for p in packets)
                    state = await self.reload()
                    assert state.spatial is not None
                    assert state.spatial["positions"][self.players[0]] == destination
                round_number = state.round_number
                await self.command(
                    "declare_phase",
                    {
                        "declarations": [
                            {
                                "kind": "attack",
                                "actor_id": self.players[0],
                                "action": "Longsword",
                                "target_id": enemy,
                                "held_item_id": "",
                                "rider": "",
                            },
                            *[
                                {"kind": "defend", "actor_id": p.id}
                                for p in state.participants
                                if p.id != self.players[0] and not p.is_fallen
                            ],
                        ]
                    },
                )
                for _ in range(12):
                    result = await self.command("resolve_phase", {})
                    if self.sd.combat_state is None or result.get("round_complete"):
                        break
                    state = await self.reload()
                    if state.round_number != round_number:
                        break
                if self.sd.combat_state is None:
                    break
        assert self.sd.combat_state is None
        assert await self.pool.fetchval("SELECT 1 FROM combat_instances WHERE combat_id=$1", combat_id) is None
        ended = [p for p in published_payloads(self.sd.room) if p["type"] == E.COMBAT_ENDED]
        assert ended and ended[-1]["outcome"] == "victory"
