from acceptance.mawling_harness import MawlingHarness
from livekit.agents import Agent, AgentSession

import db_mutations
import db_queries
from check_tools import check
from choice_tools import select
from fate_tool_boundary import wrap_tool
from mode_tools import enter_mode
from movement_tools import move_player
from query_tools import query_info
from scene_tools import enter_location

ENTRANCE = "greyvale_ruins_entrance"
INNER = "greyvale_ruins_inner"
TOKEN = "ressa_corrow_scout_token"
SCOUT = "hollowed_scout"
TORIN = "guildmaster_torin"
HALL = "accord_guild_hall"
REPORT = {"choice_id": "lost_scout_report", "option": "report"}


class ScoutHarness(MawlingHarness):
    async def fresh_session(self):
        await self.session.aclose()
        self.session = AgentSession(llm=self.model, max_tool_steps=5, userdata=self.sd)
        await self.session.start(self.explorer())

    def explorer(self):
        return Agent(
            instructions="Execute the command.",
            tools=[enter_mode, wrap_tool(query_info), enter_location, check, move_player, select],
        )

    async def search(self, target="scattered rubble", skill="investigation"):
        return await self.command(
            "check", {"roll": {"kind": "discover", "skill": skill, "target": target, "hearing_only": False}}
        )

    async def enter(self, location):
        return await self.command("move_player", {"destination_id": location})

    async def scene(self):
        return await self.command("enter_location", {"location_id": self.sd.location_id})

    async def stage_at(self, location):
        await db_mutations.update_player_location(self.players[0], location)
        self.sd.location_id = location

    async def torin(self):
        return await self.command("query_info", {"kind": "npc", "target_id": TORIN})

    async def flags(self):
        player = await db_queries.get_player(self.players[0])
        assert player is not None
        return player["flags"]

    async def start_scout(self):
        await self.search()
        offer = (await self.enter(INNER))["lost_scout"]
        return await self.command("enter_mode", offer["entry"])

    async def declare_scout(self, *actions):
        await self.command("declare_phase", {"declarations": list(actions)})

    def defend_action(self):
        return {"reshape": [], "kind": "defend", "actor_id": self.players[0]}

    def attack_action(self, *, scout_attacks=False):
        return {
            "reshape": [],
            "quick_fingers_mode": "",
            "quick_fingers_item": "",
            "kind": "attack",
            "actor_id": "hollowed_scout_1" if scout_attacks else self.players[0],
            "action": "Corrupted Blade" if scout_attacks else "Longsword",
            "target_id": self.players[0] if scout_attacks else "hollowed_scout_1",
            "held_item_id": "",
            "rider": "",
        }

    async def position_by_scout(self):
        state = await self.reload()
        assert state.spatial is not None
        state.spatial["positions"][self.players[0]] = state.spatial["positions"]["hollowed_scout_1"]
        return await self.persist()
