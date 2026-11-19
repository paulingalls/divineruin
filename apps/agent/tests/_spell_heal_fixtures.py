"""Registered spell commands with real players and combat checkpoints."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest
from _unbound_path_fixtures import MilestoneWalk
from acceptance._capstone_helpers import _build_state, _enemy, _player
from acceptance.seeds import seed_known_spells, seed_player
from voice_condition_fixtures import place_actors

import db_mutations
import db_queries
from mode_tools import enter_mode
from party_state import PartyState

WOUNDS = "divine_heal_wounds"
TOUCH = "primal_healing_touch"
MASS = "divine_mass_heal"
PRAYER = "divine_prayer_of_healing"
REGENERATE = "primal_regenerate"
LOCATION = "millhaven_inn"


class HealWalk(MilestoneWalk):
    async def patch_row(self, pid, **data):
        await self.pool.execute("UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", pid, json.dumps(data))

    async def add_player(self, *, hp=3, maximum=20, location=LOCATION, party=True):
        pid = f"heal_{uuid4().hex}"
        await seed_player(self.pool, player_id=pid, location_id=location)
        self.stack.push_async_callback(self.pool.execute, "DELETE FROM players WHERE player_id=$1", pid)
        await self.patch_row(pid, hp={"current": hp, "max": maximum})
        if party:
            self.sd.party.members.append(PartyState.solo(pid).primary)
        return pid

    async def read(self, pid, *, conn=None):
        row = await db_queries.get_player(pid, conn=conn)
        assert row is not None
        return row

    async def focus(self):
        return (await self.row())["focus"]["current"]

    async def fight(self, *, companion=False):
        state = _build_state(f"heal_{uuid4().hex}", self.player, [_enemy("foe", 100)])
        for pid in self.sd.party.member_ids:
            row = await self.read(pid)
            ally = _player(pid, row["hp"]["current"])
            ally.hp_max = row["hp"]["max"]
            ally.attributes = row["attributes"]
            if pid == self.player:
                state.participants[0] = ally
            else:
                state.participants.append(ally)
                state.initiative_order.append(pid)
        if companion:
            state.participants.append(replace(_enemy("companion", 20), type="companion", hp_current=3))
            state.initiative_order.append("companion")
        state.location_id = LOCATION
        state.terrain = "forest"
        place_actors(state)
        self.sd.combat_state = state
        self.track_fight()
        await self.save()
        return state

    @property
    def fight_state(self):
        state = self.sd.combat_state
        assert state is not None
        return state

    def track_fight(self):
        self.stack.push_async_callback(db_mutations.delete_combat_state, self.fight_state.combat_id)

    async def save(self):
        state = self.fight_state
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())

    async def checkpoint(self):
        saved = await db_mutations.load_combat_state(self.fight_state.combat_id)
        assert saved is not None
        assert saved.to_dict() == self.fight_state.to_dict()
        return saved

    async def declare(self, spell, targets, *, error=False):
        declarations = [
            {"kind": "ability", "actor_id": self.player, "action": spell, "targets": targets, "argument_type": ""}
        ]
        declarations.extend(
            {"kind": "defend", "actor_id": p.id}
            for p in self.fight_state.participants
            if p.id != self.player and not p.is_fallen
        )
        return await self.command("declare_phase", {"declarations": declarations}, error=error)

    async def wrap(self):
        packets = []
        for _ in range(8):
            result = await self.command("resolve_phase", {})
            packets.extend(result.get("packets", []))
            if result["beat"] == "declaration":
                return packets
        raise AssertionError("Combat did not reach the next declaration beat")

    async def cast(self, spell, *, targets=None, combat=False):
        if combat:
            await self.declare(spell, targets or [])
            packets = await self.wrap()
            return next(p["cast"] for p in packets if p["actor_id"] == self.player)
        selectors = (
            {} if targets is None else {"target_id": targets[0]} if len(targets) == 1 else {"target_ids": targets}
        )
        return await self.command("activate", {"id": spell, **selectors})

    async def prepare(self, spell, *, wisdom=16):
        row = await self.row()
        await self.patch(
            **{"class": "druid" if spell.startswith("primal") else "cleric"},
            level=20,
            attributes={**row["attributes"], "wisdom": wisdom},
            divine_favor=None,
            hp={"current": 3, "max": 20},
            focus={"current": 30, "max": 30},
        )
        await seed_known_spells(self.pool, self.player, (spell,))

    async def register_end(self):
        from combat_end import end_combat

        agent = self.session.current_agent
        await agent.update_tools([*agent.tools, end_combat])

    async def enter(self, mock_combat_agent_factory):
        agent = self.session.current_agent
        await agent.update_tools([*agent.tools, enter_mode])
        mock_combat_agent_factory.return_value = agent
        await self.command("enter_mode", {"mode": "combat", "encounter_id": "ruins_mawling_pair"})
        self.track_fight()


@pytest.fixture(name="healer")
async def spell_heal_walk(dev_db_pool):
    async with HealWalk(dev_db_pool) as walk:
        yield walk
