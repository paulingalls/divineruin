"""Fate's Thread across authenticated microphone turns on the combat agent."""

import asyncio
import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from _zhael_fate_fixtures import attack, defend
from acceptance._capstone_helpers import _build_state, _d20, _damage_die, _enemy, _player
from acceptance.choir_capstone_harness import ChoirEncounterDiagnostic
from acceptance.choir_capstone_voice import CHOIR_COMMAND_SPEECH, BurstSTT, TurnModel
from acceptance.multiplayer_voice._harness import MultiplayerVoiceHarness
from acceptance.multiplayer_voice.test_guest_leaves import ToneTTS
from acceptance.seeds import seed_player_with_pools
from acceptance.test_kaelen_iron_resolve_capstone import required_player
from livekit.agents import AgentSession, llm
from livekit.agents.testing import fake_job_context
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from voice_condition_fixtures import place_actors

import db
import db_mutations
import db_queries
from combat_agent import CombatAgent
from participant_lifecycle import _setup_party_join
from session_data import SessionData
from session_startup import GameplayInputOwner, gameplay_room_options


@pytest.fixture
def mock_combat_agent_factory():
    return None


class FateVoiceStream(llm.LLMStream):
    async def _run(self):
        model = cast(FateVoiceModel, self._llm)
        turns = 0
        latest = None
        for item in self._chat_ctx.items:
            if (
                isinstance(item, llm.ChatMessage)
                and item.role == "user"
                and "capstone turn " in (item.text_content or "")
            ):
                turns += 1
            elif isinstance(item, llm.FunctionCallOutput) and item.call_id in model.calls:
                model.receipts[item.call_id] = item
                latest = item
        if len(model.calls) < min(turns, len(model.commands)):
            name, arguments = model.commands[len(model.calls)]
            call_id = uuid4().hex
            model.calls[call_id] = name
            delta = llm.ChoiceDelta(
                role="assistant",
                tool_calls=[llm.FunctionToolCall(name=name, arguments=json.dumps(arguments), call_id=call_id)],
            )
        else:
            text = "Your command reaches me."
            if latest is not None and not latest.is_error and "fate_offer" in json.loads(latest.output):
                text = "Fate's Thread is yours to use. Shall I roll again?"
            delta = llm.ChoiceDelta(role="assistant", content=text)
        self._event_ch.send_nowait(llm.ChatChunk(id=uuid4().hex, delta=delta))


class FateVoiceModel(TurnModel):
    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **kwargs):
        return FateVoiceStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class RecordingTTS(ToneTTS):
    def __init__(self):
        super().__init__()
        self.spoken = []

    def synthesize(self, text, **kwargs):
        self.spoken.append(text)
        return super().synthesize(text, **kwargs)


class FateDiagnostic(ChoirEncounterDiagnostic):
    def __init__(self, player_id, guest_id):
        super().__init__(player_id)
        self.guest_id = guest_id
        self.model = FateVoiceModel([])
        self.tts = RecordingTTS()
        self.tts_patch = patch("base_agent._make_tts", return_value=self.tts)

    async def start(self, room):
        pool = await db.get_pool()
        for pid in (self.player_id, self.guest_id):
            await seed_player_with_pools(pool, player_id=pid, class_="mage")
        await pool.execute(
            "UPDATE players SET data=jsonb_set(data,'{divine_favor}',$2::jsonb) WHERE player_id=$1",
            self.guest_id,
            json.dumps({"patron": "zhael", "level": 0, "max": 100, "last_whisper_level": 0}),
        )
        self.sd = SessionData(player_id=self.player_id, location_id="accord_guild_hall")
        state = _build_state(self.player_id, self.player_id, [_enemy("foe", 30)])
        state.participants.append(_player(self.guest_id))
        state.initiative_order.insert(1, self.guest_id)
        place_actors(state)
        self.sd.combat_state = state
        self.sd.room = room
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        self.lifecycle = _setup_party_join(room, self.sd)
        self.sd.multiplayer_owner = cast(GameplayInputOwner, SimpleNamespace(lifecycle=self.lifecycle))
        self.session = AgentSession(llm=self.model, tts=self.tts, max_tool_steps=5, userdata=self.sd)
        self.tts_patch.start()
        with fake_job_context(room=room):
            await self.session.start(room=room, agent=CombatAgent(), room_options=gameplay_room_options(self.sd))


async def test_fate_attack_offer_and_choice_reach_guest_microphone(livekit_server, reset_db_pool):
    harness = MultiplayerVoiceHarness(livekit_server)
    host, guest = harness.player_one_identity, harness.player_two_identity
    encounter = FateDiagnostic(host, guest)

    async def prepare(room):
        await encounter.start(room)
        return encounter.lifecycle.authorize

    async def command(identity, name, **arguments):
        count = len(encounter.model.commands) + 1
        encounter.model.commands.append((name, arguments))
        await harness.play(identity, CHOIR_COMMAND_SPEECH)
        await encounter.wait_for_receipts(count)
        receipt = list(encounter.model.receipts.values())[-1]
        assert receipt.name == name and not receipt.is_error, receipt.output
        turn = encounter.transcripts[-1]
        assert turn.participant_identity == identity and turn.generation > 0 and turn.speech_events
        return json.loads(receipt.output)

    try:
        with (
            patch("session_summary._call_llm_summary", new_callable=AsyncMock, return_value=None),
            patch("check_resolution.dice_roll", side_effect=[_d20(1), _d20(20)]),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            await harness.start(prepare, stt=BurstSTT())
            encounter.attach(harness.manager)
            await command(host, "declare_phase", declarations=[attack(host, "foe"), defend(guest), defend("foe")])
            offered = await command(host, "resolve_phase")
            offer = offered["fate_offer"]
            assert offer["roller_id"] == host and offer["eligible_followers"] == [guest]
            assert "Any other tool call, including query_info, lets the original stand." in offered["dm_cue"]
            async with asyncio.timeout(5):
                while not any("Fate's Thread is yours" in text for text in encounter.tts.spoken):
                    await asyncio.sleep(0.02)
            assert required_player(await encounter.reload(), "foe").hp_current == 30
            args = {"id": "zhael_fates_thread", "offer_id": offer["offer_id"]}
            shown = await command(guest, "activate", **args)
            assert shown["original"]["die"] == 1 and shown["reroll"]["die"] == 20
            chosen = await command(guest, "activate", **args, keep="reroll")
            assert chosen["packets"][0]["damage"] == 8
            assert required_player(await encounter.reload(), "foe").hp_current == 22
            guest_row = await db_queries.get_player(guest)
            host_row = await db_queries.get_player(host)
            assert guest_row is not None and guest_row["patron_gifts"]["zhael_fates_thread"] == {"spent": True}
            assert host_row is not None and "zhael_fates_thread" not in host_row.get("patron_gifts", {})
            assert len(encounter.transcripts) == 4
    finally:
        try:
            await encounter.aclose()
        finally:
            await harness.aclose()
