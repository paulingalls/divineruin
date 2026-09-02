"""Assigned-companion cues emitted by background and onboarding processes."""

import re
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import event_types as E
from background_process import BackgroundProcess
from bg_speech import COMPANION_IDLE_SECS, PendingSpeech, SpeechPriority
from companion_profiles import get_companion_profile
from event_bus import GameEvent
from onboarding_background import NUDGE_DELAY_SECONDS, ONBOARDING_NUDGES, OnboardingBackgroundProcess
from session_data import CompanionState, SessionData
from system_prompts import build_companion_cue

COMPANION_IDS = (
    "companion_kael",
    "companion_lira",
    "companion_tam",
    "companion_sable",
)

EVENT_CUES = (
    ("arrival", E.LOCATION_CHANGED, {"new_location": "accord_market_square"}, True),
    ("quest", E.QUEST_UPDATED, {"quest_name": "Greyvale", "objective": "Travel north"}, True),
    ("combat-conscious", E.COMBAT_ENDED, {"outcome": "victory"}, True),
    ("combat-unconscious", E.COMBAT_ENDED, {"outcome": "victory"}, False),
    (
        "social",
        E.DISPOSITION_CHANGED,
        {"npc_name": "Emris", "previous": "neutral", "new": "friendly"},
        True,
    ),
    ("hollow-1", E.HOLLOW_CORRUPTION_CHANGED, {"level": 1}, True),
    ("hollow-2", E.HOLLOW_CORRUPTION_CHANGED, {"level": 2}, True),
    ("hollow-3", E.HOLLOW_CORRUPTION_CHANGED, {"level": 3}, True),
)

GOD_WHISPER_PAYLOAD = {"event_id": "god_whisper:player_patron", "patron_id": "kaelen"}


def _companion(companion_id: str, **changes: object) -> CompanionState:
    profile = get_companion_profile(companion_id)
    companion = CompanionState(id=profile.id, name=profile.name)
    for key, value in changes.items():
        setattr(companion, key, value)
    return companion


def _session_data(companion: CompanionState | None) -> SessionData:
    return SessionData(
        player_id="player_1",
        location_id="accord_guild_hall",
        patron_id="kaelen",
        companion=companion,
    )


def _background(sd: SessionData) -> tuple[BackgroundProcess, MagicMock]:
    agent = MagicMock()
    agent.update_instructions = AsyncMock()
    session = MagicMock()
    session.generate_reply = AsyncMock()
    return BackgroundProcess(agent, session, sd), session


def _assert_assigned_cue(instructions: str, companion_id: str) -> None:
    profile = get_companion_profile(companion_id)
    assert re.search(rf"\b{re.escape(profile.name)}\b", instructions)
    if profile.non_verbal:
        assert f"{profile.name} is non-verbal" in instructions
        assert f"[{profile.voice_id}," not in instructions
    else:
        assert f"[{profile.voice_id}," in instructions
    if companion_id != "companion_kael":
        assert re.search(r"\bKael\b", instructions) is None
        assert "COMPANION_KAEL" not in instructions


@pytest.mark.parametrize("companion_id", COMPANION_IDS)
@pytest.mark.parametrize("site,event_type,payload,is_conscious", EVENT_CUES, ids=[case[0] for case in EVENT_CUES])
def test_every_event_cue_uses_the_assigned_companion(
    companion_id: str,
    site: str,
    event_type: str,
    payload: dict,
    is_conscious: bool,
) -> None:
    del site
    companion = _companion(companion_id, is_conscious=is_conscious)
    sd = _session_data(companion)
    background, _ = _background(sd)

    background._handle_events([GameEvent(event_type=event_type, payload=payload)])

    assert len(background._speech_queue) == 1
    _assert_assigned_cue(background._speech_queue[0].instructions, companion_id)


@pytest.mark.parametrize("companion_id", COMPANION_IDS)
@pytest.mark.parametrize("site", ("idle", "guidance"))
def test_every_timer_cue_uses_the_assigned_companion(companion_id: str, site: str) -> None:
    past = time.time() - COMPANION_IDLE_SECS - 5
    companion = _companion(companion_id, last_speech_time=past)
    sd = _session_data(companion)
    sd.last_player_speech_time = past
    sd.last_agent_speech_end = past
    background, _ = _background(sd)

    if site == "idle":
        background._check_companion_idle()
    else:
        background._quest_cache = [
            {
                "quest_id": "greyvale",
                "current_stage": 0,
                "stages": [{"id": "start"}],
                "scene_graph": [{"scene_id": "road", "stage_refs": [0]}],
            }
        ]
        background._scene_cache = {
            "road": {
                "id": "road",
                "beats": [{"companion_hints": ["Head north."], "hint_delay_seconds": 1}],
            }
        }
        background._check_scene_beat_hints()

    assert len(background._speech_queue) == 1
    _assert_assigned_cue(background._speech_queue[0].instructions, companion_id)


@pytest.mark.parametrize("companion_id", COMPANION_IDS)
@pytest.mark.parametrize(
    "beat,index",
    [(beat, index) for beat, nudges in ONBOARDING_NUDGES.items() for index in range(len(nudges))],
)
@pytest.mark.asyncio
async def test_every_onboarding_nudge_uses_the_assigned_companion(
    companion_id: str,
    beat: int,
    index: int,
) -> None:
    companion = _companion(companion_id)
    sd = _session_data(companion)
    sd.onboarding_beat = beat
    sd.last_player_speech_time = time.time() - NUDGE_DELAY_SECONDS - 5
    session = MagicMock()
    session.generate_reply = AsyncMock()
    background = OnboardingBackgroundProcess(session, sd)
    background._last_active_beat = beat
    background._hint_index = index

    await background._check_nudge()

    instructions = session.generate_reply.await_args.kwargs["instructions"]
    _assert_assigned_cue(instructions, companion_id)


@pytest.mark.parametrize("companion_id", COMPANION_IDS)
@pytest.mark.asyncio
async def test_delivery_gate_recognizes_a_real_assigned_cue(companion_id: str) -> None:
    """Reader against the WRITER's own output — a reworded cue must not silently stop matching."""
    companion = _companion(companion_id, last_speech_time=0.0)
    instructions = build_companion_cue(companion, "reacts to the moment.", "steady")
    background, _ = _background(_session_data(companion))
    background._speech_queue.append(PendingSpeech(SpeechPriority.IMPORTANT, instructions))

    await background._deliver_speech()

    assert companion.last_speech_time > 0


@pytest.mark.parametrize("companion_id", COMPANION_IDS)
@pytest.mark.asyncio
async def test_delivery_gate_ignores_narration_that_is_not_a_companion_cue(companion_id: str) -> None:
    """Narration-only delivery must not reset the idle clock, or it suppresses the next
    companion beat for a full COMPANION_IDLE_SECS."""
    companion = _companion(companion_id, last_speech_time=0.0)
    background, _ = _background(_session_data(companion))
    background._speech_queue.append(
        PendingSpeech(
            SpeechPriority.IMPORTANT,
            "The player just arrived at a new location (accord_market_square). Describe the atmosphere briefly.",
        )
    )

    await background._deliver_speech()

    assert companion.last_speech_time == 0.0


@pytest.mark.parametrize("companion_id", COMPANION_IDS)
def test_god_whisper_names_the_assigned_companion_and_keeps_it_silent(companion_id: str) -> None:
    """The whisper is a CRITICAL divine beat: the companion is named but must NOT be cued to
    speak, so no dialogue tag and no non-verbal vocalization instruction may appear."""
    profile = get_companion_profile(companion_id)
    background, _ = _background(_session_data(_companion(companion_id)))

    background._handle_events([GameEvent(E.WORLD_EVENT, GOD_WHISPER_PAYLOAD)])

    instructions = background._speech_queue[0].instructions
    assert re.search(rf"\b{re.escape(profile.name)}\b", instructions)
    assert "says nothing unless the player speaks first" in instructions
    assert f"[{profile.voice_id}," not in instructions
    assert f"{profile.name} is non-verbal" not in instructions
    if companion_id != "companion_kael":
        assert re.search(r"\bKael\b", instructions) is None


def test_god_whisper_without_companion_omits_companion_reaction() -> None:
    background, _ = _background(_session_data(None))

    background._handle_events([GameEvent(E.WORLD_EVENT, GOD_WHISPER_PAYLOAD)])

    instructions = background._speech_queue[0].instructions
    assert "companion" not in instructions.lower()
    assert re.search(r"\bKael\b", instructions) is None


@pytest.mark.asyncio
async def test_onboarding_nudge_without_companion_logs_and_keeps_polling(caplog: pytest.LogCaptureFixture) -> None:
    sd = _session_data(None)
    sd.onboarding_beat = 4
    sd.last_player_speech_time = time.time() - NUDGE_DELAY_SECONDS - 5
    session = MagicMock()
    session.generate_reply = AsyncMock()
    background = OnboardingBackgroundProcess(session, sd)

    with caplog.at_level("ERROR", logger="divineruin.onboarding_background"):
        await background._check_nudge()

    session.generate_reply.assert_not_awaited()
    assert "without a companion" in caplog.text
