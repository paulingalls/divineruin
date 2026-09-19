from __future__ import annotations

import json
import math
from pathlib import Path

import jwt
import pytest

from native_transport_probe import (
    SESSION_INIT_FIXTURE,
    assert_mobile_result,
    build_tone_frames,
    mint_probe_token,
    safe_result,
)


def test_tone_is_deterministic_two_second_440hz_mono_pcm() -> None:
    frames = build_tone_frames()
    assert len(frames) == 200
    assert all(frame.sample_rate == 48_000 for frame in frames)
    assert all(frame.num_channels == 1 for frame in frames)
    assert all(frame.samples_per_channel == 480 for frame in frames)
    samples = frames[0].data
    assert samples[0] == 0
    assert samples[1] == pytest.approx(12_000 * math.sin(2 * math.pi * 440 / 48_000), abs=1)


def test_probe_token_is_room_scoped_agent_with_distinct_identity() -> None:
    token = mint_probe_token("devkey", "secret", "room-one", "python-one")
    claims = jwt.decode(token, "secret", algorithms=["HS256"], options={"verify_aud": False})
    assert claims["iss"] == "devkey"
    assert claims["sub"] == "python-one"
    assert claims["kind"] == "agent"
    assert claims["video"]["room"] == "room-one"
    assert claims["video"]["roomJoin"] is True
    assert claims["video"]["canPublish"] is True
    assert claims["video"]["canSubscribe"] is True


def test_fixture_is_the_cross_language_session_init_contract() -> None:
    disk = json.loads((Path(__file__).parent / "session_init_fixture.json").read_text())
    assert disk == SESSION_INIT_FIXTURE
    assert disk["character"]["name"] == "Upgrade Test Hero"
    assert disk["location"]["name"] == "Upgrade Test Room"


def test_mobile_result_guards_each_transport_claim_and_redacts_credentials() -> None:
    good = {
        "run_id": "run-one",
        "mobile_identity": "mobile-one",
        "publisher_identity": "python-one",
        "peer_ready": True,
        "subscribed_publisher_identity": "python-one",
        "audio_track_sid": "TR_audio",
        "packets_received": 1,
        "bytes_received": 128,
        "event_received": True,
        "event_sender_identity": "python-one",
        "hud_character": "Upgrade Test Hero",
        "hud_location": "Upgrade Test Room",
    }
    assert_mobile_result(good, "run-one", "python-one")
    for field, value, message in (
        ("run_id", "stale", "run ID"),
        ("peer_ready", False, "peer"),
        ("subscribed_publisher_identity", "wrong", "publisher"),
        ("packets_received", 0, "audio"),
        ("bytes_received", 0, "audio"),
        ("event_received", False, "SESSION_INIT"),
        ("hud_character", "", "HUD"),
    ):
        with pytest.raises(ValueError, match=message):
            assert_mobile_result({**good, field: value}, "run-one", "python-one")

    with pytest.raises(ValueError, match="credential"):
        safe_result({**good, "nested": {"token": "secret"}})
    assert safe_result(good) == good
