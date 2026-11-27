"""Public-tool driver for the Choir's home encounter."""

import json
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from random import Random, getstate, seed, setstate
from typing import Any
from unittest.mock import AsyncMock, patch

from acceptance.mawling_harness import MawlingHarness
from acceptance.voice_condition_harness import ScenarioModel
from asyncpg import Connection
from livekit.agents import Agent, AgentSession
from sample_fixtures import make_mock_room

import character_spells
import combat_spatial
import db
import db_queries
import leveling
import spells
from activate_tools import activate
from archetypes import get_archetype_chassis
from combat_agent import CombatAgent
from combat_participant import CombatParticipant
from combat_state import CombatState
from condition_restrictions import cannot_act
from conditions import has_condition
from creation_rules import build_character_data
from mode_tools import enter_mode
from progression_tools import _award_xp_core
from rules_engine import XP_FOR_LEVEL
from scene_tools import enter_location
from session_data import SessionData
from spell_voice_rules import is_silenced

HOME = "ashmark_lost_voices"
KIT = ("Stolen Melody", "Memory Scream", "Dissonant Chord", "Cacophony", "Silence Void")
Payload = dict[str, Any]


@contextmanager
def seeded_dice(value: int) -> Iterator[Random]:
    previous = getstate()
    seed(value)
    rng = Random(value)
    try:
        with patch("dice.random.SystemRandom", return_value=rng):
            yield rng
    finally:
        setstate(previous)


def ability(actor: str, action: str, target: str) -> Payload:
    return {"kind": "ability", "actor_id": actor, "action": action, "targets": [target], "argument_type": ""}


def defend(actor: str) -> Payload:
    return {"kind": "defend", "actor_id": actor, "reshape": []}


def move(actor: str, destination: Payload) -> Payload:
    return {
        "kind": "move",
        "actor_id": actor,
        "destination": destination,
        "movement_mode": "ground",
        "nythera_step": False,
        "reshape": [],
    }


def enemy_declaration(actor: str, action: Payload, target: str) -> Payload:
    if action["declaration_type"] == "ability":
        return ability(actor, action["id"], target)
    return {
        "kind": "attack",
        "actor_id": actor,
        "action": action["id"],
        "target_id": target,
        "reshape": [],
        "held_item_id": "",
        "rider": "",
        "quick_fingers_mode": "",
        "quick_fingers_item": "",
    }


class ChoirFight(MawlingHarness):
    async def setup(self) -> None:
        classes = ("cleric", "mage", "mage", "skirmisher")
        await self.prepare((1,) * len(classes), companion=None, location=HOME, tools=(activate,))
        for pid, archetype in zip(self.players, classes, strict=True):
            row = build_character_data(
                archetype, "human", archetype, None, "", created_at=datetime(2026, 11, 24, tzinfo=UTC)
            )
            row.update(player_id=pid, location_id=HOME)
            await self.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(row))
            async with db.transaction() as conn:
                await _award_xp_core(
                    player_id=pid,
                    player=row,
                    amount=XP_FOR_LEVEL[16],
                    reason="Choir challenger",
                    conn=conn,
                    pending_events=[],
                )
            promoted = await db_queries.get_player(pid)
            assert promoted is not None and promoted["level"] == 16
            for spell in {
                "mage": ("arcane_bolt", "arcane_magic_missile", "arcane_disintegrate"),
                "cleric": ("divine_sacred_flame", "divine_bless", "divine_heal_wounds", "divine_flame_strike"),
                "skirmisher": (),
            }[archetype]:
                profile = spells.get_spell(spell)
                assert profile.source == get_archetype_chassis(archetype).magic_source
                assert leveling.is_spell_tier_unlocked(archetype, profile.spell_tier, promoted["level"])
                await character_spells.record_learned(pid, spell, "training", is_prepared=True)
            for resource in ("hp", "stamina", "focus"):
                if resource in promoted:
                    promoted[resource]["current"] = promoted[resource]["max"]
            await self.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(promoted))
            assert await db_queries.get_player(pid) == promoted

    async def enter(self) -> Payload:
        home = await self.command("enter_location", {"location_id": HOME})
        assert home["location"]["id"] == HOME
        self.encounter_id = home["choir"]["encounter_id"]
        result = await self.command("enter_mode", {"mode": "combat", "encounter_id": self.encounter_id})
        assert isinstance(self.session.current_agent, CombatAgent)
        state = await self.reload()
        assert (state.location_id, state.encounter_id) == (HOME, self.encounter_id)
        owners = [p for p in state.participants if p.creature_id == "hollow_choir"]
        assert len(owners) == 1 and owners[0].role == "named"
        self.owner_id = owners[0].id
        self.combat_id = state.combat_id
        assert state.round_number == 1 and result["choir"]["phase"] == "search"
        return result

    @property
    def state(self) -> CombatState:
        state = self.sd.combat_state
        assert state is not None
        return state

    @property
    def owner(self) -> CombatParticipant:
        owner = self.state.get_participant(self.owner_id)
        assert owner is not None
        return owner

    @property
    def encounter(self) -> Payload:
        record = self.state.choir_encounter
        assert record is not None
        return record

    @property
    def publisher(self) -> AsyncMock:
        room = self.sd.room
        assert room is not None
        publish = room.local_participant.publish_data
        assert isinstance(publish, AsyncMock)
        return publish

    def roster(self, response: Payload) -> Payload:
        return next(p for p in response["participants"] if p["id"] == self.owner_id)

    async def declare(self, declarations: list[Payload], *, error: bool = False) -> Any:
        return await self.command("declare_phase", {"declarations": declarations}, error=error)

    async def player_rows(self, *, conn: Connection | None = None) -> dict[str, Payload]:
        rows = {}
        for pid in self.players:
            row = await db_queries.get_player(pid, conn=conn)
            assert row is not None
            rows[pid] = row
        return rows

    async def reopen_home(self) -> Payload:
        await self.session.aclose()
        self.sd = SessionData(player_id=self.players[0], location_id=HOME, room=make_mock_room())
        self.model = ScenarioModel([])
        self.session = AgentSession(llm=self.model, max_tool_steps=5, userdata=self.sd)
        await self.session.start(Agent(instructions="Execute the command.", tools=[enter_mode, enter_location]))
        return await self.command("enter_location", {"location_id": HOME})


def enemy_turn(h: ChoirFight, response: Payload, executions: Counter[str]) -> Payload:
    actions = {a["id"]: a for a in h.roster(response)["executable_actions"] if a["available"]}
    origin = combat_spatial.position(h.state.spatial, h.owner_id)
    if not actions:
        if is_silenced(h.state, h.owner_id):
            return move(h.owner_id, {**origin, "x": origin["x"] + 5})
        return defend(h.owner_id)
    standing = [p for p in h.state.participants if p.is_ally and not p.is_fallen and not p.is_dead]
    for name in sorted(KIT, key=lambda action: (executions[action] > 0, KIT.index(action))):
        if name not in actions:
            continue
        if executions[name] and name != "Dissonant Chord":
            continue
        targets = [
            p
            for p in standing
            if combat_spatial.inside(
                origin,
                combat_spatial.position(h.state.spatial, p.id),
                {"Dissonant Chord": 120, "Silence Void": 30}.get(name, 60),
            )
        ]
        if targets:
            target = h.players[-1] if any(p.id == h.players[-1] for p in targets) else targets[0].id
            return enemy_declaration(h.owner_id, actions[name], target)
    return defend(h.owner_id)


async def party_turn(h: ChoirFight, facts: Payload, attack: bool, kit_complete: bool) -> list[Payload]:
    declarations = []
    for pid in h.players:
        actor = h.state.get_participant(pid)
        assert actor is not None
        if (
            actor.is_fallen
            or actor.is_dead
            or cannot_act(actor.conditions)
            or has_condition(actor.conditions, "charmed")
        ):
            continue
        if is_silenced(h.state, pid):
            origin = combat_spatial.position(h.state.spatial, pid)
            declarations.append(move(pid, {**origin, "y": min(35, origin["y"] + 25)}))
        elif facts["phase"] == "search" and pid in h.players[1:3]:
            declarations.append({"kind": "interact", "actor_id": pid, "action": facts["search_actions"][1]["action"]})
        elif facts["phase"] == "exposed" and attack and pid != h.players[-1]:
            player = await db_queries.get_player(pid)
            assert player is not None
            focus = player["focus"]["current"]
            if pid == h.players[0]:
                wounded = [p for p in h.state.participants if p.is_ally and not p.is_dead and p.hp_current < 22]
                if wounded and focus >= 2:
                    declarations.append(ability(pid, "divine_heal_wounds", min(wounded, key=lambda p: p.hp_current).id))
                    continue
                spell = "divine_flame_strike" if kit_complete and focus >= 5 else "divine_sacred_flame"
            elif focus >= 7 and actor.hp_current >= 42:
                spell = "arcane_disintegrate"
            else:
                spell = "arcane_magic_missile" if focus >= 2 else "arcane_bolt"
            declarations.append(ability(pid, spell, facts["core_id"]))
        else:
            declarations.append(defend(pid))
    return declarations
