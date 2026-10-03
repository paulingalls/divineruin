"""Native microphone prerequisite; fails before encounter certification without two turns."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))

from acceptance._livekit_client import wait_for_audio_track
from acceptance.choir_capstone_voice import BurstSTT, ChoirVoiceDiagnostic
from livekit import rtc
from livekit.agents import utils

import db
from multiplayer_transcription import MultiParticipantTranscriber
from native_transport.lifecycle import run_cancellable
from native_transport_probe import ProbeState, run_probe


async def receive_commands(room: rtc.Room, identity: str, state: ProbeState, evidence_path: Path) -> int:
    diagnostic = ChoirVoiceDiagnostic(identity)
    manager = monitor = None
    frames = peak = 0

    async def observe_audio():
        nonlocal frames, peak
        track = await wait_for_audio_track(room, identity=identity)
        stream = rtc.AudioStream(track)
        try:
            async for event in stream:
                frames += 1
                peak = max(peak, max(abs(sample) for sample in event.frame.data))
                state.set_microphone_frames(frames)
        finally:
            await stream.aclose()

    try:
        async with utils.http_context.open():
            await diagnostic.start(room)
            assert diagnostic.lifecycle is not None
            manager = MultiParticipantTranscriber(room, stt=BurstSTT(), authorizer=diagnostic.lifecycle.authorize)
            manager.start()
            diagnostic.attach(manager)
            monitor = asyncio.create_task(observe_audio())
            await diagnostic.wait_for_receipts(1)
            await diagnostic.assert_refusal_unchanged()
            await diagnostic.wait_for_receipts(2)
            diagnostic.assert_complete()
            return frames
    finally:
        try:
            evidence_path.write_text(
                json.dumps(
                    {
                        "microphone_frames": frames,
                        "peak_amplitude": peak,
                        "authenticated_turns": [
                            {"identity": turn.participant_identity, "text": turn.text, "generation": turn.generation}
                            for turn in diagnostic.transcripts
                        ],
                        "commands": list(diagnostic.model.calls.values()),
                        "receipts": [
                            {"name": receipt.name, "is_error": receipt.is_error, "output": receipt.output}
                            for receipt in diagnostic.model.receipts.values()
                        ],
                    },
                    indent=2,
                )
                + "\n"
            )
        finally:
            try:
                if monitor is not None:
                    monitor.cancel()
                    await asyncio.gather(monitor, return_exceptions=True)
            finally:
                try:
                    await diagnostic.aclose()
                finally:
                    if manager is not None:
                        await manager.aclose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fault", choices=("none",), default="none")
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    async def exercise():
        async def receiver(room, identity, state):
            return await receive_commands(room, identity, state, args.result.with_name("microphone-turns.json"))

        transport_path = args.result.with_name("transport.json")
        try:
            await run_probe(args.run_id, args.fault, args.control, transport_path, receiver)
        finally:
            await db.close_all()
        result = json.loads(transport_path.read_text())
        result["microphone_turns"] = json.loads(args.result.with_name("microphone-turns.json").read_text())
        args.result.write_text(json.dumps(result, indent=2) + "\n")

    asyncio.run(run_cancellable(exercise))


if __name__ == "__main__":
    main()
