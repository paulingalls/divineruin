import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from _zhael_fate_fixtures import defend, game_tools
from acceptance.seeds import seed_player
from sample_fixtures import FixedRng, make_context, make_mock_room
from test_aelora_gift import _live_party

import character_spells
import db
import db_mutations
import dice
from caster_state import ConcentrationState, ResonanceTrack
from combat_agent import CombatAgent
from exploration_agent import ExplorationAgent
from mode_tools import enter_mode
from party_state import PartyMember

ORDINARY = "ruins_mawling_pair"
RESTORE_KEYS = ("hp", "temp_hp", "stamina", "focus", "resonance", "concentration", "patron_gifts")
RESET_FLAGS = ("weapon_used", "weapon_crit_vs_heavy", "draethar_inner_fire_used", "unbound_raw_channeling_used")


class Fight:
    def __init__(self, pool) -> None:
        self.pool = pool
        self.ids = []
        self.combats = []
        self.lifecycle = None

    async def add_player(self, location: str, *, mage: bool = False) -> str:
        pid = f"checkpoint_{uuid4().hex}"
        self.ids.append(pid)
        await seed_player(self.pool, player_id=pid, class_="mage" if mage else "warrior", location_id=location)
        index = len(self.ids)
        await self.pool.execute(
            "UPDATE players SET data = data || $2::jsonb WHERE player_id=$1",
            pid,
            json.dumps(
                {
                    "equipment": {
                        "main_hand": {
                            "name": "Guild Longsword",
                            "damage": "1d8",
                            "damage_type": "slashing",
                            "properties": [],
                        }
                    }
                    if index == 1
                    else {},
                    "stamina": {"current": 3 + index, "max": 10},
                    "focus": {"current": index, "max": 10},
                    "temp_hp": index,
                    "resonance": {"current": 3 + index},
                    "concentration": None,
                    "patron_gifts": {"test": {"spent": True}},
                    "flags": {"ignored": True, **({"shadow_veil": True, "concealed": True} if index == 1 else {})},
                }
            ),
        )
        if mage:
            await self.pool.execute(
                "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
                pid,
                json.dumps(
                    {
                        "level": 5,
                        "race": "human",
                        "focus": {"current": 10, "max": 10},
                        "resonance": {"current": 9},
                        "unbound_autonomy": {"level": 75, "max": 100, "tier": "Sovereign"},
                        "divine_favor": {"patron": "none", "level": 0, "max": 100},
                    }
                ),
            )
            await self.pool.execute(
                "INSERT INTO player_inventory (player_id,item_id,data) VALUES ($1,$2,$3::jsonb)",
                pid,
                "healing_potion_minor",
                json.dumps({"quantity": 2}),
            )
            await character_spells.record_learned(pid, "arcane_haste", "training", is_prepared=True, conn=self.pool)
        if index <= 2:
            for tainted in (False, True) if index == 1 else (False,):
                await self.pool.execute(
                    "INSERT INTO player_inventory (player_id,item_id,tainted,data) VALUES ($1,$2,$3,$4::jsonb)",
                    pid,
                    "longsword_guild",
                    tainted,
                    json.dumps({"current_hits": index + int(tainted), "quantity": 1, "equipped": not tainted}),
                )
        return pid

    async def prepare(self, location: str, *, mage: bool = False) -> None:
        await self.add_player(location)
        await self.add_player(location, mage=mage)
        self.session = make_context(self.ids[0], location, room=make_mock_room(), party_member_ids=self.ids).userdata
        for index, member in enumerate(self.session.party.members):
            for name in RESET_FLAGS:
                setattr(member, name, True)
            member.unbound_veil_mastery_used = bool(index)
            member.resonance.current = 4 + index
        if mage:
            guest = self.session.member_state(self.ids[1])
            guest.resonance.current = 9
            guest.unbound_veil_mastery_used = False
        self.lifecycle = _live_party(self.session, *self.ids)

    async def invoke(self, call, name: str, *, actor: str | None = None, **arguments):
        actor = actor or self.ids[0]
        lifecycle = self.lifecycle
        assert lifecycle is not None
        generation = await lifecycle.authorize(actor)
        assert generation is not None
        with self.session._bind_authenticated_actor(actor, generation, lifecycle.require_authorized):
            return await call(name, **arguments)

    async def call(self, name: str, **arguments):
        return await self.invoke(self.tools, name, **arguments)

    async def start(self, encounter: str = ORDINARY) -> dict:
        call = game_tools(self.session, enter_mode)
        agent, result = await self.invoke(call, "enter_mode", mode="combat", encounter_id=encounter)
        self.combats.append(self.session.combat_state.combat_id)
        assert isinstance(agent, CombatAgent)
        self.tools = game_tools(self.session, agent=agent)
        return result

    async def declare(self, *declarations: dict) -> None:
        await self.call(
            "declare_phase",
            declarations=list(declarations)
            or [
                defend(p.id)
                for p in self.session.combat_state.participants
                if not p.is_structure and (self.session.combat_state.still_encounter is None or p.type != "enemy")
            ],
        )

    async def join(self) -> str:
        pid = await self.add_player(self.session.location_id)
        self.session.party.members.append(PartyMember(pid, ResonanceTrack(), ConcentrationState()))
        return pid

    async def reload(self) -> dict:
        state = await db_mutations.load_combat_state(self.combats[-1], conn=self.pool)
        assert state is not None
        self.session.combat_state = state
        return await self.row()

    async def finish_round(self, next_round: int) -> None:
        for _ in range(20):
            state = self.session.combat_state
            if (
                state.round_number == next_round
                and state.beat == "declaration"
                and not (state.held_actions or state.open_window or state.wrap_continuation)
            ):
                return
            await self.call("resolve_phase")
        pytest.fail(f"Round {next_round} did not open")

    async def write_row(self, row: dict) -> None:
        await db_mutations.save_combat_state(self.combats[-1], row, conn=self.pool)

    async def row(self) -> dict:
        raw = await self.pool.fetchval("SELECT data FROM combat_instances WHERE combat_id=$1", self.combats[-1])
        return json.loads(raw)

    async def assert_snapshot(self, row: dict) -> None:
        image = dict(row)
        history = image.pop("round_checkpoints")
        snapshot = history[-1]
        assert (snapshot["combat_id"], snapshot["round_number"]) == (image["combat_id"], image["round_number"])
        assert snapshot["combat"] == image
        assert snapshot["players"].keys() == set(self.ids)
        for pid in self.ids:
            raw = json.loads(await self.pool.fetchval("SELECT data FROM players WHERE player_id=$1", pid))
            expected = {key: raw[key] for key in RESTORE_KEYS if key in raw}
            flags = raw.get("flags", {})
            if captured := {key: flags[key] for key in ("shadow_veil", "concealed") if key in flags}:
                expected["flags"] = captured
            slots = await self.pool.fetch(
                "SELECT item_id, tainted, data FROM player_inventory WHERE player_id=$1 ORDER BY item_id, tainted", pid
            )
            member = self.session.member_state(pid)
            assert snapshot["players"][pid] == {
                "data": expected,
                "inventory": [dict(slot, data=json.loads(slot["data"])) for slot in slots],
                "session_flags": {
                    **{name: getattr(member, name) for name in RESET_FLAGS},
                    "unbound_veil_mastery_used": member.unbound_veil_mastery_used,
                },
            }


@pytest.fixture
def mock_combat_agent_factory() -> None:
    pass


@pytest.fixture(name="fight")
async def checkpoint_fight(dev_db_pool, monkeypatch) -> AsyncIterator[Fight]:
    monkeypatch.setattr(db, "_cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(db, "_cache_set", AsyncMock())
    monkeypatch.setattr(dice, "random", SimpleNamespace(SystemRandom=lambda: FixedRng(1)))
    monkeypatch.setattr("combat_end._build_handoff_agent", lambda *_: ExplorationAgent())
    world = Fight(dev_db_pool)
    try:
        yield world
    finally:
        if world.lifecycle is not None:
            await world.lifecycle.aclose()
        await dev_db_pool.execute("DELETE FROM combat_instances WHERE combat_id=ANY($1::text[])", world.combats)
        await dev_db_pool.execute("DELETE FROM players WHERE player_id=ANY($1::text[])", world.ids)
