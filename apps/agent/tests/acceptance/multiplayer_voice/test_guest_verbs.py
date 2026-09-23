from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from acceptance.multiplayer_voice._harness import MultiplayerVoiceHarness
from acceptance.seeds import seed_player_with_pools
from livekit import rtc
from livekit.agents import Agent, AgentSession, llm
from livekit.agents.testing import fake_job_context
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from sample_fixtures import FixedRng

import check_resolution
import db
import db_mutations
import milestones
from activate_tools import activate
from activity_tools import begin_activity
from check_tools import check
from combat_end import end_combat
from multiplayer_input import MultiplayerInput
from multiplayer_transcription import AuthenticatedTranscript
from participant_lifecycle import PartyLifecycle, _setup_party_join
from query_tools import query_info
from quest_tools import update_quest
from session_data import CombatParticipant, CombatState, SessionData
from session_startup import gameplay_room_options
from travel_tools import travel

CALLS = [
    ("activate", {"id": "warrior_second_wind"}),
    ("check", {"roll": {"kind": "social", "npc_id": "guildmaster_torin", "skill": "persuasion", "difficulty": "easy"}}),
    ("query_info", {"kind": "inventory"}),
    ("begin_activity", {"activity": {"kind": "training", "program_id": "combat_basics"}}),
    ("travel", {"destination_id": "greyvale_ruins_exterior", "mode": "scenic"}),
    ("update_quest", {"quest_id": "greyvale_anomaly", "new_stage_id": 5}),
    ("end_combat", {"outcome": "victory"}),
]
TOOLS: list[llm.Tool | llm.Toolset] = [activate, check, query_info, begin_activity, travel, update_quest, end_combat]


class ScriptedStream(llm.LLMStream):
    def __init__(self, model: ScriptedModel, **kwargs: Any) -> None:
        super().__init__(model, **kwargs)
        self.model = model

    async def _run(self) -> None:
        last = self.chat_ctx.items[-1]
        request_id = uuid.uuid4().hex
        if isinstance(last, llm.ChatMessage) and last.role == "user":
            name, args = CALLS[self.model.completed_turns]
            call = llm.FunctionToolCall(name=name, arguments=json.dumps(args), call_id=f"guest-{request_id}")
            delta = llm.ChoiceDelta(role="assistant", tool_calls=[call])
        else:
            self.model.completed_turns += 1
            delta = llm.ChoiceDelta(role="assistant", content="Done.")
        self._event_ch.send_nowait(llm.ChatChunk(id=request_id, delta=delta))


class ScriptedModel(llm.LLM):
    def __init__(self) -> None:
        super().__init__()
        self.completed_turns = 0

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **_kwargs) -> llm.LLMStream:
        return ScriptedStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class TranscriptQueue:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[AuthenticatedTranscript] = asyncio.Queue()

    async def receive(self) -> AuthenticatedTranscript:
        return await self.queue.get()


async def _player(pool, player_id: str) -> dict:
    data = await pool.fetchval("SELECT data FROM players WHERE player_id = $1", player_id)
    assert data is not None
    return json.loads(data)


async def _disposition(pool, player_id: str) -> str:
    data = await pool.fetchval(
        "SELECT data FROM npc_dispositions WHERE player_id = $1 AND npc_id = 'guildmaster_torin'", player_id
    )
    return json.loads(data)["disposition"]


async def test_guest_verbs_reach_persisted_party_rows(
    livekit_server: dict[str, str], reset_db_pool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolve = check_resolution.resolve_skill_check_dc
    monkeypatch.setattr(
        check_resolution,
        "resolve_skill_check_dc",
        lambda player, skill, dc, rng=None: resolve(player, skill, dc, FixedRng(20)),
    )
    pool = await db.get_pool()
    harness = MultiplayerVoiceHarness(livekit_server)
    host, guest = harness.player_one_identity, harness.player_two_identity
    for player_id in (host, guest):
        await seed_player_with_pools(pool, player_id=player_id, class_="warrior")
        await pool.execute(
            "UPDATE players SET data = jsonb_set(data, '{xp}', $2::jsonb) WHERE player_id = $1",
            player_id,
            "100" if player_id == host else "200",
        )
        await pool.execute(
            "INSERT INTO npc_dispositions (npc_id, player_id, data) VALUES ('guildmaster_torin', $1, $2::jsonb)",
            player_id,
            json.dumps({"disposition": "hostile" if player_id == guest else "friendly"}),
        )
    await pool.execute("UPDATE players SET data = jsonb_set(data, '{level}', '6'::jsonb) WHERE player_id = $1", guest)
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{attributes,wisdom}', $2::jsonb) WHERE player_id = $1",
        guest,
        "20",
    )
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{attributes,wisdom}', $2::jsonb) WHERE player_id = $1",
        host,
        "3",
    )
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{divine_favor}', $2::jsonb) WHERE player_id = $1",
        guest,
        json.dumps({"patron": "kaelen", "level": 10, "max": 100, "last_whisper_level": 10}),
    )
    await db_mutations.add_inventory_item(guest, "healing_potion", 2, conn=pool)
    await milestones.load_milestones()
    userdata = SessionData(player_id=host, location_id="accord_guild_hall")
    model = ScriptedModel()
    transcripts = TranscriptQueue()
    dm_session: AgentSession | None = None
    multiplayer_input: MultiplayerInput | None = None
    lifecycle: PartyLifecycle | None = None

    async def prepare_listener(room: rtc.Room):
        nonlocal dm_session, lifecycle
        lifecycle = _setup_party_join(room, userdata)
        dm_session = AgentSession(llm=model, max_tool_steps=5, userdata=userdata)
        dm_session.output.set_audio_enabled(False)
        with fake_job_context(room=room):
            await dm_session.start(
                room=room,
                agent=Agent(instructions="Call the requested tool once.", tools=TOOLS),
                room_options=gameplay_room_options(userdata),
            )
        return lifecycle.authorize

    async def turn(index: int, generation: int) -> str:
        assert dm_session is not None and lifecycle is not None
        name = CALLS[index][0]
        assert any(getattr(tool, "__name__", None) == name for tool in dm_session.current_agent.tools)
        await transcripts.queue.put(AuthenticatedTranscript(guest, f"Guest asks for {name}", generation))
        try:
            async with asyncio.timeout(20):
                while model.completed_turns <= index:
                    await asyncio.sleep(0.02)
        except TimeoutError as exc:
            raise TimeoutError(
                f"{name} stalled: completed={model.completed_turns}, history={dm_session.history.items}"
            ) from exc
        calls = [item for item in dm_session.history.items if isinstance(item, llm.FunctionCall)]
        outputs = [item for item in dm_session.history.items if isinstance(item, llm.FunctionCallOutput)]
        assert len(calls) == index + 1 and calls[-1].name == name, calls
        assert len(outputs) == index + 1 and not outputs[-1].is_error, outputs
        return outputs[-1].output

    try:
        await harness.start(prepare_listener, transcribe=False)
        assert lifecycle is not None and dm_session is not None
        assert dm_session.stt is None and dm_session.tts is None
        generation = await lifecycle.authorize(guest)
        assert generation is not None and set(userdata.party.member_ids) == {host, guest}
        multiplayer_input = MultiplayerInput(transcripts, lifecycle, dm_session, userdata)
        multiplayer_input.start()
        await transcripts.queue.put(AuthenticatedTranscript(guest, "Stale guest request", generation + 1))
        async with asyncio.timeout(2):
            while not transcripts.queue.empty():
                await asyncio.sleep(0.01)
        await asyncio.sleep(0.1)
        assert model.completed_turns == 0
        assert not any(isinstance(item, llm.ChatMessage) and item.role == "user" for item in dm_session.history.items)

        host_before, guest_before = await _player(pool, host), await _player(pool, guest)
        activated = json.loads(await turn(0, generation))
        host_after, guest_after = await _player(pool, host), await _player(pool, guest)
        assert (
            guest_before["stamina"]["current"] - guest_after["stamina"]["current"]
            == activated["deducted"]["stamina"]
            == 4
        )
        assert guest_before["focus"]["current"] - guest_after["focus"]["current"] == activated["deducted"]["focus"] == 0
        assert host_after["stamina"] == host_before["stamina"]
        assert host_after["focus"] == host_before["focus"]

        host_before, guest_before = await _disposition(pool, host), await _disposition(pool, guest)
        await turn(1, generation)
        assert await _disposition(pool, guest) != guest_before
        assert await _disposition(pool, host) == host_before

        players_before = (await _player(pool, host), await _player(pool, guest))
        before = await pool.fetch(
            "SELECT player_id, item_id, data FROM player_inventory WHERE player_id = ANY($1::text[]) ORDER BY player_id, item_id",
            [host, guest],
        )
        output = await turn(2, generation)
        assert "Healing Potion" in output
        assert (await _player(pool, host), await _player(pool, guest)) == players_before
        assert (
            await pool.fetch(
                "SELECT player_id, item_id, data FROM player_inventory WHERE player_id = ANY($1::text[]) ORDER BY player_id, item_id",
                [host, guest],
            )
            == before
        )

        await turn(3, generation)
        rows = await pool.fetch(
            "SELECT player_id, state FROM training_activities WHERE player_id = ANY($1::text[])", [host, guest]
        )
        assert [(row["player_id"], row["state"]) for row in rows] == [(guest, "running_first_half")]

        await pool.execute(
            "UPDATE players SET data = jsonb_set(data, '{location_id}', $2::jsonb) WHERE player_id = ANY($1::text[])",
            [host, guest],
            json.dumps("greyvale_south_road"),
        )
        userdata.location_id = "greyvale_south_road"
        outsider = f"outsider-{uuid.uuid4().hex[:8]}"
        await seed_player_with_pools(pool, player_id=outsider)
        outsider_before = await _player(pool, outsider)
        travel_output = json.loads(await turn(4, generation))
        assert travel_output["total"] > 20
        assert (await _player(pool, host))["location_id"] == "greyvale_ruins_exterior"
        assert (await _player(pool, guest))["location_id"] == "greyvale_ruins_exterior"
        assert await _player(pool, outsider) == outsider_before

        for player_id in (host, guest):
            await db_mutations.set_player_quest(
                player_id, "greyvale_anomaly", {"current_stage": 4, "quest_name": "The Greyvale Anomaly"}
            )
        host_before, guest_before = await _player(pool, host), await _player(pool, guest)
        quest_output = json.loads(await turn(5, generation))
        assert any(reward["type"] == "favor" for reward in quest_output["rewards_applied"])
        for player_id, before_player in ((host, host_before), (guest, guest_before)):
            quest = await pool.fetchval(
                "SELECT data FROM player_quests WHERE player_id = $1 AND quest_id = 'greyvale_anomaly'", player_id
            )
            assert json.loads(quest)["current_stage"] == 5
            assert json.loads(quest)["status"] == "completed"
            assert (await _player(pool, player_id))["xp"] == before_player["xp"] + 150

        enemy = CombatParticipant(
            id="guest_enemy",
            name="Foe",
            type="enemy",
            initiative=8,
            hp_current=0,
            hp_max=14,
            ac=12,
            xp_value=90,
            is_fallen=True,
            role="standard",
            category="humanoid",
        )
        players = [
            CombatParticipant(id=pid, name=pid, type="player", initiative=15, hp_current=18, hp_max=18, ac=14)
            for pid in (host, guest)
        ]
        combat = CombatState(
            combat_id=f"guest-combat-{uuid.uuid4().hex[:8]}",
            participants=[*players, enemy],
            initiative_order=[host, guest, enemy.id],
            location_id=userdata.location_id,
        )
        userdata.combat_state = combat
        await db_mutations.save_combat_state(combat.combat_id, combat.to_dict(), conn=pool)
        host_before, guest_before = await _player(pool, host), await _player(pool, guest)
        await turn(6, generation)
        assert await pool.fetchval("SELECT 1 FROM combat_instances WHERE combat_id = $1", combat.combat_id) is None
        assert (await _player(pool, host))["xp"] > host_before["xp"]
        assert (await _player(pool, guest))["xp"] > guest_before["xp"]
        assert await _player(pool, outsider) == outsider_before
    finally:
        if multiplayer_input is not None:
            await multiplayer_input.aclose()
        if dm_session is not None:
            await dm_session.aclose()
        if lifecycle is not None:
            await lifecycle.aclose()
        await harness.aclose()
