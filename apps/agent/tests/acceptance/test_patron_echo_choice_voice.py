"""Authenticated microphone turns reach the actual combat select registration."""

import asyncio
import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from acceptance._livekit_client import register_data_packet_collector
from acceptance.choir_capstone_harness import ChoirEncounterDiagnostic
from acceptance.choir_capstone_voice import CHOIR_COMMAND_SPEECH, BurstSTT
from acceptance.multiplayer_voice._harness import MultiplayerVoiceHarness
from acceptance.multiplayer_voice.test_guest_leaves import ToneTTS
from acceptance.seeds import seed_player_with_pools
from acceptance.test_voice_condition_commands import scene
from livekit.agents import AgentSession
from livekit.agents.testing import fake_job_context

import db
import db_mutations
from combat_agent import CombatAgent
from participant_lifecycle import _setup_party_join
from session_data import SessionData
from session_startup import GameplayInputOwner, gameplay_room_options


@pytest.fixture
def mock_combat_agent_factory():
    return None


class EchoDiagnostic(ChoirEncounterDiagnostic):
    async def start(self, room):
        pool = await db.get_pool()
        await seed_player_with_pools(pool, player_id=self.player_id, class_="mage", known_spells=("arcane_bolt",))
        await pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
            self.player_id,
            json.dumps({"divine_favor": {"patron": "zhael"}}),
        )
        self.sd = SessionData(player_id=self.player_id, location_id="accord_guild_hall")
        self.sd.resonance.current = 9
        state = scene(self.player_id, "outside-observer", "outside_cast")
        state.participants[1].type = "enemy"
        self.sd.combat_state = state
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        self.sd.room = room
        self.lifecycle = _setup_party_join(room, self.sd)
        self.sd.multiplayer_owner = cast(GameplayInputOwner, SimpleNamespace(lifecycle=self.lifecycle))
        self.session = AgentSession(llm=self.model, tts=ToneTTS(), max_tool_steps=5, userdata=self.sd)
        self.tts_patch.start()
        with fake_job_context(room=room):
            await self.session.start(room=room, agent=CombatAgent(), room_options=gameplay_room_options(self.sd))


async def test_voice_offers_both_then_selects_on_later_authenticated_turn(livekit_server, reset_db_pool):
    harness = MultiplayerVoiceHarness(livekit_server)
    encounter = EchoDiagnostic(harness.player_one_identity)
    events = asyncio.Queue()

    async def prepare(room):
        await seed_player_with_pools(await db.get_pool(), player_id=harness.player_two_identity)
        await encounter.start(room)
        return encounter.lifecycle.authorize

    async def speak():
        await harness.play(harness.player_one_identity, CHOIR_COMMAND_SPEECH)

    received = []

    def echoes():
        while not events.empty():
            data, _ = events.get_nowait()
            received.append(json.loads(data))
        return [event for event in received if event.get("type") == "hollow_echo_result"]

    try:
        with (
            patch("session_summary._call_llm_summary", new_callable=AsyncMock, return_value=None),
            patch("dice.roll", side_effect=[SimpleNamespace(total=18), SimpleNamespace(total=1)]),
        ):
            await harness.start(prepare, stt=BurstSTT())
            assert harness.player_one is not None
            register_data_packet_collector(harness.player_one, queue=events, topic="game_events")
            encounter.attach(harness.manager)
            declaration = await encounter.command(
                "declare_phase",
                {
                    "declarations": [
                        {
                            "kind": "ability",
                            "actor_id": encounter.player_id,
                            "action": "arcane_bolt",
                            "targets": [],
                            "argument_type": "",
                        },
                        {
                            "kind": "defend",
                            "actor_id": "outside-observer",
                            "action": "defend",
                            "targets": [],
                            "argument_type": "",
                        },
                    ]
                },
                speak,
            )
            assert not declaration.is_error, declaration.output
            resolved = await encounter.command("resolve_phase", {}, speak)
            assert not resolved.is_error, resolved.output
            packet = json.loads(resolved.output)
            offer = next(p["cast"]["pending_choice"] for p in packet["packets"] if "cast" in p)
            assert [o["band"] for o in offer["options"]] == ["nothing", "breach"]
            assert not echoes()
            chosen = await encounter.command("select", {"choice_id": offer["choice_id"], "option": "second"}, speak)
            assert not chosen.is_error, chosen.output
            assert json.loads(chosen.output)["hollow_echo"]["band"] == "breach"
            async with asyncio.timeout(5):
                while not echoes():
                    await asyncio.sleep(0.02)
            assert len(echoes()) == 1
            assert echoes()[0] == {"type": "hollow_echo_result", "band": "breach"}
            assert len(encounter.transcripts) == 3
    finally:
        await encounter.aclose()
        await harness.aclose()
