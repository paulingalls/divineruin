"""Checkout-owned rows and deterministic IO for Unbound boundary tests."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sample_fixtures import make_context, make_mock_room

import db_queries
import spell_casting
from activate_tools import _activate_impl
from combat_participant import CombatParticipant
from combat_state import CombatState


@pytest.fixture
async def world(dev_db_pool):
    ids = ["unbound_" + uuid4().hex for _ in range(2)]
    for pid in ids:
        await dev_db_pool.execute(
            "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb)",
            pid,
            json.dumps(
                {
                    "class": "mage",
                    "level": 5,
                    "race": "human",
                    "focus": {"current": 100},
                    "resonance": {"current": 9},
                    "divine_favor": {"patron": "none", "level": 0, "max": 100},
                }
            ),
        )

    @asynccontextmanager
    async def transaction():
        async with dev_db_pool.acquire() as conn, conn.transaction():
            yield conn

    ctx = make_context(player_id=ids[0], party_member_ids=[ids[1]], room=make_mock_room())
    for member in ctx.userdata.party.members:
        member.resonance.current = 9
    w = SimpleNamespace(ids=ids, pool=dev_db_pool, db=SimpleNamespace(transaction=transaction), ctx=ctx)
    try:
        yield w
    finally:
        await dev_db_pool.execute("DELETE FROM players WHERE player_id = ANY($1)", ids)


def encounter(w):
    w.ctx.userdata.combat_state = CombatState(
        combat_id="unbound_encounter",
        participants=[
            CombatParticipant(id=pid, name=pid, type="player", initiative=10, hp_current=20, hp_max=20, ac=14)
            for pid in w.ids
        ],
        initiative_order=w.ids,
    )


async def cast(w, *, sid="arcane_bolt", roll=1, database=None, echo=None, die=None, ward=False):
    async def entry(ctx, spell_id, **kw):
        return await spell_casting._cast_spell_impl(
            ctx,
            spell_id,
            **kw,
            db_mod=database or w.db,
            character_spells_mod=MagicMock(get_known=AsyncMock(return_value=[{"spell_id": sid}])),
            ward_resolution_mod=MagicMock(resolve_scope_ward=AsyncMock(return_value={} if ward else None)),
            dice_mod=die or MagicMock(roll=MagicMock(return_value=SimpleNamespace(total=roll))),
            **({"echo_events_mod": echo} if echo else {}),
        )

    return json.loads(await _activate_impl(w.ctx, sid, cast_spell_mod=MagicMock(_cast_spell_impl=entry)))


async def push(w, *, database=None, token="unbound_raw_channeling"):
    import unbound_tools

    with patch.object(unbound_tools.db, "transaction", (database or w.db).transaction):
        return json.loads(await _activate_impl(w.ctx, token))


async def row(w, index=1):
    player = await db_queries.get_player(w.ids[index], conn=w.pool)
    assert player is not None
    return player


async def phase(w, *, database=None, echo=None, declare=True):
    from functools import partial

    from combat._helpers import _resolve_deps
    from voice_condition_fixtures import place_actors

    import combat_turn
    import db_mutations_resonance

    state = w.ctx.userdata.combat_state
    if declare:
        place_actors(state)
        state.beat = "declaration"
        declarations = {pid: {"type": "defend"} for pid in w.ids}
        declarations[w.ids[1]] = {"type": "ability", "action": "arcane_fireball"}
        await combat_turn._declare_phase_impl(w.ctx, declarations, mutations=MagicMock(save_combat_state=AsyncMock()))
    known = MagicMock(get_known=AsyncMock(return_value=[{"spell_id": "arcane_fireball"}]))
    resolver = SimpleNamespace(
        _gate_spell=spell_casting._gate_spell,
        _resolve_cast=partial(
            spell_casting._resolve_cast,
            character_spells_mod=known,
            ward_resolution_mod=MagicMock(resolve_scope_ward=AsyncMock(return_value=None)),
            dice_mod=MagicMock(roll=MagicMock(return_value=SimpleNamespace(total=1))),
            **({"echo_events_mod": echo} if echo else {}),
        ),
    )
    deps: dict = _resolve_deps()
    deps.update(
        db_mod=database or w.db,
        queries=db_queries,
        cast_resolver=resolver,
        character_spells_mod=known,
        resonance_mutations=db_mutations_resonance,
    )
    raw = await combat_turn._resolve_phase_impl(w.ctx, **deps)
    assert isinstance(raw, str), "combat ended unexpectedly"
    return json.loads(raw)


class MilestoneWalk:
    """Extend the durable command harness with saves and phase commands."""

    def __new__(cls, pool):
        from patron_ability_walk import AbilityWalk

        class Walk(AbilityWalk):
            async def connect(self, sd=None):
                from acceptance.voice_condition_harness import ScenarioModel
                from livekit.agents import Agent, AgentSession

                from activate_tools import activate
                from check_tools import check
                from combat_turn import declare_phase, resolve_phase
                from query_tools import query_info
                from rest_tools import rest
                from session_data import SessionData

                self.sd = sd or SessionData(player_id=self.player, location_id="millhaven_inn", room=make_mock_room())
                self.model = ScenarioModel([])
                self.session = AgentSession(llm=self.model, userdata=self.sd)
                await self.session.start(
                    Agent(
                        instructions="Execute the command.",
                        tools=[activate, query_info, check, rest, declare_phase, resolve_phase],
                    )
                )
                self.stack.push_async_callback(self.session.aclose)

        return Walk(pool)
