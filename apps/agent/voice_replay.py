from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import random
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

from livekit import api, rtc
from livekit.agents import AgentSession, inference
from livekit.agents.utils import http_context
from livekit.agents.voice.events import FunctionToolsExecutedEvent
from livekit.agents.voice.room_io import RoomOptions
from livekit.plugins import deepgram

import check_resolution
import db
from base_agent import BaseGameAgent, _make_tts
from exploration_agent import EXPLORATION_TOOLS
from gameplay_llm import LUNA_MODEL, create_gameplay_llm, is_luna
from session_data import SessionData
from system_prompts import build_system_prompt
from voice_replay_audio import (
    CheckedClip,
    ReceivedAudio,
    cancel_task,
    capture_received_audio,
    close_room,
    close_source,
    load_checked_clip,
    publish_checked_audio,
    wait_for_output,
    write_wav,
)
from voice_replay_metrics import (
    TranscribedWord,
    compute_audio_metrics,
    normalized_words,
    summarize_provider_usage,
    validate_timing_row,
)
from voice_replay_scope import REPLAY_ENDPOINTING_SECONDS, REPLAY_INSTRUCTION, VOICE_REPLAY_SCOPE
from voices import INWORLD_MODEL

AGENT_IDENTITY = "voice-replay-agent"
PLAYER_IDENTITY = "voice-replay-player"
PLAYER_ID = "voice_replay_luna"
QUEUE_SIZE_MS = 100


class FixedRng(random.Random):
    def randint(self, a: int, b: int) -> int:
        del a, b
        return 20


def append_evidence_row(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(row, sort_keys=True, default=str) + "\n"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


async def execute_with_evidence(
    operation: Callable[[dict[str, Any]], Awaitable[None]],
    owned_closers: list[Callable[[], Awaitable[None]]],
    evidence_path: Path,
    row: dict[str, Any],
    validate: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    row.setdefault("completion", "failed")
    error: BaseException | None = None
    try:
        await operation(row)
        row["completion"] = "success"
        row["diagnostic"] = ""
    except BaseException as exc:
        error = exc
        row["completion"] = "failed"
        row["diagnostic"] = f"{type(exc).__name__}: {exc}"
        task = asyncio.current_task()
        if task is not None:
            while task.cancelling():
                task.uncancel()
    cleanup_errors = []
    for close in reversed(owned_closers):
        try:
            await close()
        except BaseException as exc:
            cleanup_errors.append(f"{type(exc).__name__}: {exc}")
    row["cleanup"] = {"complete": not cleanup_errors, "errors": cleanup_errors}
    if cleanup_errors:
        row["completion"] = "failed"
        row["diagnostic"] = row.get("diagnostic") or "owned cleanup failed"
    if error is None and validate is not None:
        try:
            validate(row)
        except BaseException as exc:
            error = exc
            row["completion"] = "failed"
            row["diagnostic"] = f"{type(exc).__name__}: {exc}"
    append_evidence_row(evidence_path, row)
    if error is not None:
        raise error
    if cleanup_errors:
        raise RuntimeError(f"owned cleanup failed: {cleanup_errors}")


async def inventory_quantities(pool: Any, player_id: str) -> dict[str, int]:
    rows = await pool.fetch("SELECT item_id, data FROM player_inventory WHERE player_id = $1", player_id)
    return {row["item_id"]: json.loads(row["data"]).get("quantity", 0) for row in rows}


async def assert_inventory_result(
    pool: Any, player_id: str, before: dict[str, int], tool_output: dict[str, Any]
) -> dict[str, int]:
    materials = tool_output.get("materials")
    if not isinstance(materials, list) or not materials or any(not isinstance(item, str) for item in materials):
        raise AssertionError(f"gather tool returned an invalid material multiset: {materials!r}")
    after = await inventory_quantities(pool, player_id)
    changed = {
        item: after.get(item, 0) - before.get(item, 0)
        for item in set(before) | set(after)
        if after.get(item, 0) != before.get(item, 0)
    }
    expected = dict(Counter(materials))
    if changed != expected:
        raise AssertionError(f"inventory delta {changed!r} did not equal gather result {expected!r}")
    return changed


async def reset_seed(pool: Any, player_id: str) -> dict[str, int]:
    await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
    data = {
        "player_id": player_id,
        "name": "Voice Replay",
        "level": 2,
        "class": "skirmisher",
        "location_id": "greyvale_south_road",
        "attributes": {
            "strength": 12,
            "dexterity": 16,
            "constitution": 14,
            "intelligence": 10,
            "wisdom": 13,
            "charisma": 8,
        },
        "proficiencies": ["stealth", "perception"],
        "saving_throw_proficiencies": ["strength", "dexterity"],
        "hp": {"current": 28, "max": 28},
        "ac": 15,
    }
    await pool.execute("INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb)", player_id, json.dumps(data))
    await pool.execute(
        "INSERT INTO skill_advancement (player_id, skill_id, tier, use_counter, narrative_moment_ready) "
        "VALUES ($1, 'survival', 'master', 0, FALSE)",
        player_id,
    )
    return await inventory_quantities(pool, player_id)


def _evidence_dir(override: Path | None) -> Path:
    if override is not None:
        return override.resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "worktrees":
            return parent.parent / "evidence" / "strict-voice-sprint103"
    raise RuntimeError("cannot resolve DATA evidence directory; pass --output-dir")


def _validate_credentials() -> None:
    required = (
        "OPENAI_API_KEY",
        "DEEPGRAM_API_KEY",
        "INWORLD_API_KEY",
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "DATABASE_URL",
    )
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError(f"missing live voice replay credentials: {', '.join(missing)}")


async def _connect(room_name: str, identity: str, *, agent: bool = False) -> rtc.Room:
    grants = api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_publish_data=True,
        can_subscribe=True,
    )
    token = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_name(identity)
        .with_grants(grants)
        .with_ttl(timedelta(seconds=300))
        .with_kind("agent" if agent else "standard")
        .to_jwt()
    )
    room = rtc.Room()
    await room.connect(os.environ["LIVEKIT_URL"], token)
    return room


async def _transcribe(received: ReceivedAudio, metrics: list[Any]) -> tuple[str, list[TranscribedWord]]:
    recognizer = deepgram.STT(model="nova-3", language="en")
    recognizer.on("metrics_collected", metrics.append)
    frames = []
    for span in received.frames:
        payload = received.pcm[span.start_sample * 2 : span.end_sample * 2]
        frames.append(
            rtc.AudioFrame(
                data=payload,
                sample_rate=received.sample_rate,
                num_channels=1,
                samples_per_channel=span.end_sample - span.start_sample,
            )
        )
    try:
        event = await recognizer.recognize(frames)
    finally:
        await recognizer.aclose()
    if not event.alternatives:
        raise ValueError("Deepgram returned no alternatives for received audio")
    alternative = event.alternatives[0]
    if not alternative.words:
        raise ValueError("Deepgram returned no words for received audio")
    words = [TranscribedWord(str(w), cast(float, w.start_time), cast(float, w.end_time)) for w in alternative.words]
    return alternative.text, words


async def _run_row(
    *, scenario: str, repetition: int, clip: CheckedClip, evidence_dir: Path, evidence_path: Path, timeout: float
) -> None:
    row: dict[str, Any] = {
        "scenario": scenario,
        "repetition": repetition,
        "temperature": "cold" if repetition == 0 else "warm",
        "completion": "failed",
        "measurement_scope": dict(VOICE_REPLAY_SCOPE),
    }
    closers: list[Callable[[], Awaitable[None]]] = []

    async def operation(row: dict[str, Any]) -> None:
        pool = await db.get_pool()
        before = await reset_seed(pool, PLAYER_ID)
        row["state_before"] = {"inventory": before}
        room_name = f"voice-replay-{uuid4().hex}"
        agent_room = await _connect(room_name, AGENT_IDENTITY, agent=True)
        closers.append(lambda: close_room(agent_room))
        player_room = await _connect(room_name, PLAYER_IDENTITY)
        closers.append(lambda: close_room(player_room))

        source = rtc.AudioSource(clip.sample_rate, clip.channels, queue_size_ms=QUEUE_SIZE_MS)
        closers.append(lambda: close_source(source))
        track = rtc.LocalAudioTrack.create_audio_track("checked-player-input", source)
        options = rtc.TrackPublishOptions()
        options.source = rtc.TrackSource.SOURCE_MICROPHONE
        await player_room.local_participant.publish_track(track, options)

        selected = create_gameplay_llm("unused")
        if not is_luna(selected) or getattr(selected, "model", None) != LUNA_MODEL:
            raise RuntimeError("voice replay gameplay model is not the pinned Luna model")
        session_stt = deepgram.STT(model="nova-3", language="en")
        configured_tts = _make_tts()
        tts_instances: list[Any] = []
        tts_metrics: list[Any] = []

        def observe_tts(instance: Any) -> None:
            instance.on("metrics_collected", tts_metrics.append)
            tts_instances.append(instance)
            closers.append(instance.aclose)

        transcript_path = evidence_dir / f"{scenario}-{repetition}-{uuid4().hex[:8]}.transcript.log"
        userdata = SessionData(
            player_id=PLAYER_ID,
            location_id="greyvale_south_road",
            room=agent_room,
            transcript_path=str(transcript_path),
        )
        session = AgentSession(
            stt=session_stt,
            llm=selected,
            tts=configured_tts,
            vad=inference.VAD(model="silero", min_silence_duration=0.5),
            turn_handling={
                "turn_detection": inference.TurnDetector(),
                "endpointing": {"min_delay": REPLAY_ENDPOINTING_SECONDS},
                "interruption": {"enabled": True},
            },
            max_tool_steps=5,
            userdata=userdata,
        )
        closers.extend([configured_tts.aclose, selected.aclose, session.aclose])
        tools = EXPLORATION_TOOLS if scenario == "affected" else []
        agent = BaseGameAgent(
            instructions=build_system_prompt(userdata.location_id) + REPLAY_INSTRUCTION,
            tools=tools,
            tts_instance_callback=observe_tts,
        )
        final_transcripts: list[str] = []
        tool_events: list[FunctionToolsExecutedEvent] = []
        model_text: list[str] = []
        session.on(
            "user_input_transcribed",
            lambda event: final_transcripts.append(event.transcript) if event.is_final else None,
        )
        session.on("function_tools_executed", tool_events.append)

        def conversation(event: Any) -> None:
            item = event.item
            if getattr(item, "role", None) == "assistant":
                model_text.extend(part for part in item.content if isinstance(part, str))

        session.on("conversation_item_added", conversation)
        await session.start(
            agent,
            room=agent_room,
            room_options=RoomOptions(participant_identity=PLAYER_IDENTITY, close_on_disconnect=False),
        )
        stop_capture = asyncio.Event()
        capture_task = asyncio.create_task(
            capture_received_audio(
                player_room,
                publisher_identity=AGENT_IDENTITY,
                stop=stop_capture,
                timeout=timeout,
            )
        )
        closers.append(lambda: cancel_task(capture_task))
        original_resolve = check_resolution.resolve_skill_check_dc

        def resolver(player, skill, dc, rng=None):
            return original_resolve(player, skill, dc, FixedRng())

        with patch("check_resolution.resolve_skill_check_dc", side_effect=resolver):
            published = await publish_checked_audio(
                source,
                clip,
                queue_size_ms=QUEUE_SIZE_MS,
                max_queue_ms=150.0,
            )
            await wait_for_output(session, affected=scenario == "affected", tool_events=tool_events, timeout=timeout)
        stop_capture.set()
        received = await capture_task

        normalized_input = normalized_words(" ".join(final_transcripts))
        if normalized_input != normalized_words(clip.transcript):
            raise ValueError(f"input STT transcript mismatch: {final_transcripts!r}")
        wav_path = evidence_dir / f"{scenario}-{repetition}-{uuid4().hex[:8]}.received.wav"
        received_sha = write_wav(wav_path, received.pcm, sample_rate=received.sample_rate)
        analysis_metrics: list[Any] = []
        received_text, words = await _transcribe(received, analysis_metrics)
        calls = [call for event in tool_events for call in event.function_calls]
        outputs = [output for event in tool_events for output in event.function_call_outputs]
        row.update(tool_count=len(calls), tool_names=[call.name for call in calls])
        tool_output: dict[str, Any] = {}
        if scenario == "affected":
            if len(calls) != 1 or calls[0].name != "check" or len(outputs) != 1 or outputs[0].is_error:
                raise ValueError(
                    f"affected row requires one successful check call, got {[call.name for call in calls]}"
                )
            arguments = json.loads(calls[0].arguments)
            tool_output = json.loads(outputs[0].output)
            row.update(tool_arguments=arguments, tool_output=tool_output)
            if arguments.get("roll", {}).get("kind") != "gather":
                raise ValueError(f"affected check was not gather: {arguments!r}")
            delta = await assert_inventory_result(pool, PLAYER_ID, before, tool_output)
        else:
            if calls or await inventory_quantities(pool, PLAYER_ID) != before:
                raise ValueError("direct row executed a tool or mutated inventory")
            delta = {}
        after = await inventory_quantities(pool, PLAYER_ID)
        row.update(
            source_audio={
                "path": str(clip.path),
                "sha256": clip.sha256,
                "pcm_sha256": clip.pcm_sha256,
                "published_pcm_sha256": published.published_pcm_sha256,
                "published_bytes": published.published_bytes,
                "speech_end_monotonic": published.speech_end_monotonic,
                "queue_size_ms": published.queue_size_ms,
                "max_queued_duration_ms": published.max_queued_duration_ms,
            },
            received_audio={
                "path": str(wav_path),
                "sha256": received_sha,
                "bytes": len(received.pcm),
                "sample_rate": received.sample_rate,
                "publisher_identity": received.publisher_identity,
                "track_sid": received.track_sid,
                "transcript": received_text,
                "words": [dataclasses.asdict(word) for word in words],
            },
            provider_usage=summarize_provider_usage(
                session.usage.model_usage,
                tts_metrics,
                analysis_metrics,
                luna_model=LUNA_MODEL,
                inworld_model=INWORLD_MODEL,
            ),
            tool_output=tool_output,
            state_after={"inventory": after},
            state_delta=delta,
        )
        metrics = compute_audio_metrics(
            pcm=received.pcm,
            sample_rate=received.sample_rate,
            frames=received.frames,
            words=words,
            source_speech_end_monotonic=published.speech_end_monotonic,
            silence_threshold=clip.silence_threshold,
            outcome_anchor=clip.outcome_anchor if scenario == "affected" else None,
            input_transcript=clip.transcript,
        )
        row["metrics"] = {
            "first_meaningful_word": metrics.first_meaningful_word,
            "first_meaningful_latency_ms": metrics.first_meaningful_latency_ms,
            **({"outcome_latency_ms": metrics.outcome_latency_ms} if scenario == "affected" else {}),
            "pre_outcome_words": metrics.pre_outcome_words,
            "outcome_words": metrics.outcome_words,
            "result_boundary_sample": metrics.result_boundary_sample,
        }
        row["model_text"] = " ".join(model_text)

    await execute_with_evidence(operation, closers, evidence_path, row, validate=validate_timing_row)


async def run(args: argparse.Namespace) -> None:
    _validate_credentials()
    clip = load_checked_clip(args.clip)
    if clip.model != INWORLD_MODEL:
        raise ValueError(f"checked clip model {clip.model!r} is not {INWORLD_MODEL!r}")
    os.environ["GAMEPLAY_LLM"] = "openai-luna"
    evidence_dir = _evidence_dir(args.output_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / f"voice-replay-{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}.jsonl"
    failures = []
    try:
        for repetition in range(args.runs):
            for scenario in ("affected", "direct"):
                try:
                    await _run_row(
                        scenario=scenario,
                        repetition=repetition,
                        clip=clip,
                        evidence_dir=evidence_dir,
                        evidence_path=evidence_path,
                        timeout=args.timeout,
                    )
                except BaseException as exc:
                    # An interrupt must end the whole replay, not be filed as one row's failure.
                    if args.require_live or isinstance(exc, asyncio.CancelledError | KeyboardInterrupt):
                        raise
                    failures.append(f"{scenario}[{repetition}]: {type(exc).__name__}: {exc}")
    finally:
        await db.close_all()
    if failures:
        raise RuntimeError("; ".join(failures))
    print(evidence_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure player-received Luna voice timing")
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--clip", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.runs <= 0 or args.timeout <= 0:
        parser.error("--runs and --timeout must be positive")
    return args


if __name__ == "__main__":

    async def main() -> None:
        async with http_context.open():
            await run(parse_args())

    asyncio.run(main())
