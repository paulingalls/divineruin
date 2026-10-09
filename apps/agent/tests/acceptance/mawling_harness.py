"""Roomless deterministic commands through the real LiveKit tool boundary."""

import json
from uuid import uuid4

from acceptance.choir_capstone_harness import reseed_choir_content
from acceptance.seeds import seed_player_with_pools
from acceptance.voice_condition_harness import ScenarioModel
from livekit.agents import Agent, AgentSession
from sample_fixtures import make_mock_room

import db
import db_mutations
import db_queries
from caster_state import ConcentrationState, ResonanceTrack
from combat_agent import CombatAgent
from mode_tools import enter_mode
from party_state import PartyMember
from session_data import CompanionState, SessionData


class MawlingHarness:
    async def start(self, reactions=False, gear=False, companion=False):
        self.pool = await db.get_pool()
        await reseed_choir_content(self.pool)
        self.players = [f"maw147_{uuid4().hex}" for _ in range(2)]
        for index, pid in enumerate(self.players):
            await seed_player_with_pools(
                self.pool,
                player_id=pid,
                known_spells=("arcane_bolt",),
                class_=(
                    "guardian"
                    if index == 0 and reactions == "shield"
                    else "rogue"
                    if index == 0
                    else "guardian"
                    if reactions == "isolation"
                    else "cleric"
                )
                if reactions
                else "mage",
            )
            row = await db_queries.get_player(pid)
            assert row is not None
            row.update(hp={"current": 100, "max": 100}, level=8)
            await self.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(row))
        if gear:
            for pid in self.players:
                for item_id, equipped in (
                    ("shortsword_basic", True),
                    ("veil_ward_anchor_large", True),
                    ("chain_mail", True),
                    ("club_wooden", False),
                ):
                    await self.pool.execute(
                        "INSERT INTO player_inventory (player_id, item_id, data) VALUES ($1,$2,$3::jsonb)",
                        pid,
                        item_id,
                        json.dumps(
                            {
                                "equipped": equipped,
                                "current_hits": {"shortsword_basic": 10, "club_wooden": 3}.get(item_id, 25),
                            }
                        ),
                    )
                weapon = json.loads(await self.pool.fetchval("SELECT data FROM items WHERE id='shortsword_basic'"))
                row = await db_queries.get_player(pid)
                assert row is not None
                row["equipment"] = {
                    "main_hand": {
                        "name": weapon["name"],
                        "damage": weapon["damage_dice"],
                        "damage_type": weapon["effects"][0]["damage_type"],
                        "properties": weapon["properties"],
                    }
                }
                await self.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(row))
        self.sd = SessionData(player_id=self.players[0], location_id="accord_guild_hall", room=make_mock_room())
        if companion:
            self.sd.companion = CompanionState(id="companion_kael", name="Kael", player_level=8)
        self.sd.party.members.append(PartyMember(self.players[1], ResonanceTrack(), ConcentrationState()))
        self.model = ScenarioModel([])
        self.session = AgentSession(llm=self.model, max_tool_steps=5, userdata=self.sd)
        await self.session.start(Agent(instructions="Execute the command.", tools=[enter_mode]))
        result = await self.command("enter_mode", {"mode": "combat", "encounter_id": "ruins_mawling_pair"})
        assert isinstance(self.session.current_agent, CombatAgent)
        self.roster = result["participants"]
        self.enemies = [p["id"] for p in self.roster if p["type"] == "enemy"]
        return self

    async def command(self, name, arguments, *, error=False):
        self.model.commands.append((name, arguments))
        with self.sd._bind_authenticated_actor(self.players[0], 1, lambda *_: None):
            await self.session.run(user_input="Execute the next command.")
        receipt = list(self.model.receipts.values())[-1]
        assert receipt.name == name and receipt.is_error is error, receipt.output
        return receipt.output if error else json.loads(receipt.output)

    def composite(self, targets):
        actor = next(p for p in self.roster if p["id"] == self.enemies[0])
        action = next(a for a in actor["executable_actions"] if a["kind"] == "multiattack")
        return {
            "kind": "multiattack",
            "actor_id": actor["id"],
            "action": action["id"],
            "strikes": [
                {"action": s["action"], "target_id": t, "held_item_id": ""}
                for s, t in zip(action["strikes"], targets, strict=True)
            ],
        }

    async def declare(self, targets):
        return await self.command(
            "declare_phase",
            {
                "declarations": [
                    self.composite(targets),
                    *[{"kind": "defend", "actor_id": p} for p in [*self.players, self.enemies[1]]],
                ]
            },
        )

    async def reload(self):
        state = self.sd.combat_state
        assert state is not None
        persisted = await db_mutations.load_combat_state(state.combat_id)
        assert persisted is not None and persisted.to_dict() == state.to_dict()
        self.sd.combat_state = persisted
        return persisted

    async def snapshot(self):
        state = await self.reload()
        return state.to_dict(), [await db_queries.get_player(p) for p in self.players]

    async def close(self):
        await self.session.aclose()
        if self.sd.background is not None:
            await self.sd.background.stop()
        if self.sd.combat_state is not None:
            await db_mutations.delete_combat_state(self.sd.combat_state.combat_id)
        for pid in self.players:
            await self.pool.execute("DELETE FROM players WHERE player_id=$1", pid)
