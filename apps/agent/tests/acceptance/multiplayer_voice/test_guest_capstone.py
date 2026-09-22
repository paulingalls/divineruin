from __future__ import annotations

import asyncio
import json
import os

import pytest
from acceptance._live_voice import has_live_voice_key
from acceptance.multiplayer_voice._harness import MultiplayerVoiceHarness, SpeechFixture
from acceptance.seeds import seed_player_with_pools
from livekit import rtc
from livekit.agents import AgentSession, llm
from livekit.agents.testing import fake_job_context

import db
from gameplay_agent import create_gameplay_agent
from gameplay_llm import LUNA_MODEL, create_gameplay_llm
from multiplayer_input import MultiplayerInput
from participant_lifecycle import PartyLifecycle, _setup_party_join
from session_data import SessionData
from session_startup import gameplay_room_options

pytestmark = [
    pytest.mark.openai_real_llm,
    pytest.mark.live_voice,
    pytest.mark.skipif(
        os.environ.get("ALLOW_PAID_TESTS") == "1"
        and not has_live_voice_key(os.environ)
        and not os.environ.get("REQUIRE_REAL_LLM"),
        reason="guest capstone needs DEEPGRAM_API_KEY for real speech",
    ),
]

# Local macOS `say -v Samantha -r 155`, converted to 16 kHz mono PCM with ffmpeg.
GUEST_REQUESTS = SpeechFixture(
    filename="player_two_guest_turns.wav",
    utterance_id="guest-check-training-travel",
    transcript=(
        "I ask guildmaster Torin for advice. Please make an easy persuasion check. "
        "I begin physical training in combat basics. "
        "Let us take the scenic road to Greyvale ruins exterior."
    ),
    sha256="7ff29f1bdc703ce5b94cd29aa66f56e256737bbeb1587a9aabd4a3edbf4782db",
)


@pytest.fixture(autouse=True)
def _require_default_luna_key(monkeypatch: pytest.MonkeyPatch) -> None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key or key.lower().startswith("your-"):
        if os.environ.get("REQUIRE_REAL_LLM"):
            pytest.fail("REQUIRE_REAL_LLM=1 but OPENAI_API_KEY is absent, empty, or a your-... placeholder")
        pytest.skip("guest capstone needs OPENAI_API_KEY")
    monkeypatch.delenv("GAMEPLAY_LLM", raising=False)


async def test_guest_speech_drives_luna_check_activity_and_travel(
    livekit_server: dict[str, str], reset_db_pool: str
) -> None:
    pool = await db.get_pool()
    harness = MultiplayerVoiceHarness(livekit_server)
    host, guest = harness.player_one_identity, harness.player_two_identity
    for player_id in (host, guest):
        await seed_player_with_pools(pool, player_id=player_id, class_="warrior")
        await pool.execute(
            "UPDATE players SET data = jsonb_set(data, '{location_id}', '\"greyvale_south_road\"'::jsonb) WHERE player_id = $1",
            player_id,
        )
    await pool.execute(
        "INSERT INTO npc_dispositions (npc_id, player_id, data) VALUES ('guildmaster_torin', $1, $2::jsonb)",
        guest,
        json.dumps({"disposition": "hostile"}),
    )
    userdata = SessionData(player_id=host, location_id="greyvale_south_road")
    selected = create_gameplay_llm("unused-anthropic-model")
    assert selected.model == LUNA_MODEL
    dm_session: AgentSession | None = None
    multiplayer_input: MultiplayerInput | None = None
    lifecycle: PartyLifecycle | None = None
    heard: list[tuple[str, str]] = []

    async def prepare_listener(room: rtc.Room):
        nonlocal dm_session, lifecycle
        userdata.room = room
        lifecycle = _setup_party_join(room, userdata)
        dm_session = AgentSession(llm=selected, max_tool_steps=5, userdata=userdata)
        dm_session.output.set_audio_enabled(False)
        with fake_job_context(room=room):
            await dm_session.start(
                room=room,
                agent=create_gameplay_agent("wilderness", userdata.location_id),
                room_options=gameplay_room_options(userdata),
            )
        return lifecycle.authorize

    try:
        await harness.start(prepare_listener)
        assert dm_session is not None and lifecycle is not None and harness.manager is not None
        assert await lifecycle.authorize(guest) is not None
        multiplayer_input = MultiplayerInput(
            harness.manager,
            lifecycle,
            dm_session,
            userdata,
            observe_player_speech=lambda _events, identity, transcript: heard.append((identity, transcript)),
        )
        multiplayer_input.start()
        await harness.play(guest, GUEST_REQUESTS)
        try:
            async with asyncio.timeout(90):
                while True:
                    calls = [item for item in dm_session.history.items if isinstance(item, llm.FunctionCall)]
                    names = [call.name for call in calls]
                    outputs = [item for item in dm_session.history.items if isinstance(item, llm.FunctionCallOutput)]
                    if all(
                        any(
                            call.name == name and any(output.call_id == call.call_id for output in outputs)
                            for call in calls
                        )
                        for name in ("check", "begin_activity", "travel")
                    ):
                        break
                    await asyncio.sleep(0.1)
        except TimeoutError as exc:
            raise TimeoutError(
                f"guest calls stalled: heard={heard}, calls={names}, history={dm_session.history.items}"
            ) from exc
        assert heard and all(identity == guest for identity, _ in heard)
        assert names.index("check") < names.index("begin_activity") < names.index("travel"), names
        for name in ("check", "begin_activity", "travel"):
            call = next(call for call in calls if call.name == name)
            outputs = [
                item
                for item in dm_session.history.items
                if isinstance(item, llm.FunctionCallOutput) and item.call_id == call.call_id
            ]
            assert len(outputs) == 1 and not outputs[0].is_error, (name, outputs)
        assert json.loads(next(call for call in calls if call.name == "check").arguments)["roll"]["kind"] == "social"
        assert (
            json.loads(next(call for call in calls if call.name == "begin_activity").arguments)["activity"]["kind"]
            == "training"
        )
        assert json.loads(next(call for call in calls if call.name == "travel").arguments)["mode"] == "scenic"
        disposition = await pool.fetchval(
            "SELECT data FROM npc_dispositions WHERE player_id = $1 AND npc_id = 'guildmaster_torin'", guest
        )
        assert json.loads(disposition)["disposition"] != "hostile"
        assert (
            await pool.fetchval(
                "SELECT data FROM npc_dispositions WHERE player_id = $1 AND npc_id = 'guildmaster_torin'", host
            )
            is None
        )
        assert (
            await pool.fetchval("SELECT state FROM training_activities WHERE player_id = $1", guest)
            == "running_first_half"
        )
        assert await pool.fetchval("SELECT state FROM training_activities WHERE player_id = $1", host) is None
        for player_id in (host, guest):
            row = await pool.fetchval("SELECT data FROM players WHERE player_id = $1", player_id)
            assert json.loads(row)["location_id"] == "greyvale_ruins_exterior"
    finally:
        if multiplayer_input is not None:
            await multiplayer_input.aclose()
        if dm_session is not None:
            await dm_session.aclose()
        if lifecycle is not None:
            await lifecycle.aclose()
        await harness.aclose()
