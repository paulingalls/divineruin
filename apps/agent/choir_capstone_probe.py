"""Native acoustic commands, public Choir mechanics and applied client checkpoints."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))

from acceptance._livekit_client import wait_for_audio_track
from acceptance.choir_capstone_flow import ChoirCapstoneFlow
from acceptance.choir_capstone_harness import ChoirEncounterDiagnostic
from acceptance.choir_capstone_voice import OwnedStimulusSTT
from livekit import rtc
from livekit.agents import utils

import db
import db_mutations
import db_queries
from game_events import publish_game_event
from multiplayer_transcription import MultiParticipantTranscriber
from native_transport.lifecycle import run_cancellable
from native_transport_probe import SESSION_INIT_FIXTURE, ProbeState, run_probe


async def receive_commands(room: rtc.Room, identity: str, state: ProbeState, evidence_path: Path, fault="none") -> int:
    diagnostic = ChoirEncounterDiagnostic(identity)
    events = asyncio.Queue()
    native_checkpoints = {}
    flow = None
    fault_failure = None
    manager = monitor = native_monitor = None
    frames = peak = 0
    speech = OwnedStimulusSTT(state.fixture["run_id"])

    async def observe_native():
        delivered = 0
        while True:
            result = state.mobile_result or {}
            observation = result.get("native_observation", {})
            packets = observation.get("events", [])
            for event in packets[delivered:]:
                await events.put((json.dumps(event).encode(), room.local_participant.identity))
            delivered = len(packets)
            await asyncio.sleep(0.02)

    async def play():
        assert diagnostic.session is not None
        speech_handle = diagnostic.session.current_speech
        if speech_handle is not None:
            await speech_handle.wait_for_playout()
        state.extra_status.update(
            requested_turn=len(diagnostic.model.commands), command_receipts=len(diagnostic.model.receipts)
        )

    async def checkpoint(step, expected):
        if fault == "skip-encounter":
            raise AssertionError("missing named Choir encounter checkpoint")
        state.extra_status["choir_checkpoint"] = step
        async with asyncio.timeout(90):
            while (state.mobile_result or {}).get("native_checkpoint", {}).get("step") != step:
                await asyncio.sleep(0.02)
        assert state.mobile_result is not None
        actual = state.mobile_result["native_checkpoint"]
        assert actual["player"] == identity, "native checkpoint has wrong owner"
        if step not in ("destruction", "replay"):
            assert actual["combat_active"] is True, "native receiver did not apply combat"
            combat = actual.get("combat")
            assert combat and combat["combatants"], "native receiver has no combatants"
            actors = {actor["id"]: actor for actor in combat["combatants"]}
            assert actors[identity]["hpCurrent"] == expected["player_hp"], "native receiver has stale player HP"
            assert actors[expected["owner"]]["hpCurrent"] == expected["core_hp"], "native receiver has stale core HP"
            if step == "deafened":
                assert any(c["type"] == "deafened" for c in actors[identity]["conditions"]), (
                    "native receiver missed Deafened"
                )
        else:
            assert actual["combat_active"] is False and actual["combat"] is None, (
                "native receiver retained destroyed combat"
            )
            assert actual["xp"] == (expected["xp"] if "xp" in expected else native_checkpoints["destruction"]["xp"]), (
                "native receiver missed award"
            )
        if step == "cast-aura":
            assert actual["resonance"] == diagnostic.sd.member_state(identity).resonance.state, (
                "native receiver missed Resonance"
            )
        assert actual["events"], "empty native gameplay receipt"
        native_checkpoints[step] = actual
        state.extra_status["choir_checkpoint"] = ""

    async def observe_audio():
        nonlocal frames, peak
        track = await wait_for_audio_track(room, identity=identity)
        stream = rtc.AudioStream(track)
        try:
            async for event in stream:
                frames += 1
                peak = max(peak, max(abs(sample) for sample in event.frame.data))
                if speech.sources:
                    state.set_microphone_frames(frames)
                    state.extra_status["acoustic_status"] = [
                        {
                            "frames": source.frames,
                            "peak": source.last_peak,
                            "turn": source.turn,
                            "symbols": source.observed_symbols[-17:],
                        }
                        for source in speech.sources
                    ]
        finally:
            await stream.aclose()

    try:
        async with utils.http_context.open():
            await diagnostic.start(room)
            assert diagnostic.lifecycle is not None
            manager = MultiParticipantTranscriber(room, stt=speech, authorizer=diagnostic.lifecycle.authorize)
            manager.start()
            diagnostic.attach(manager)
            monitor = asyncio.create_task(observe_audio())
            native_monitor = asyncio.create_task(observe_native())
            player = await db_queries.get_player(identity)
            assert player is not None
            hydration = json.loads(json.dumps(SESSION_INIT_FIXTURE))
            hydration["character"].update(player_id=identity, hp=player["hp"], xp=player["xp"], level=player["level"])
            await publish_game_event(room, "session_init", hydration)
            flow = ChoirCapstoneFlow(diagnostic, play, events, room.local_participant.identity)
            flow.observe_checkpoint = checkpoint
            from contextlib import nullcontext
            from unittest.mock import patch

            import combat_init

            original_publish = combat_init.publish_game_event

            async def filtered_publish(room, kind, *args, **kwargs):
                if kind != "combat_started":
                    await original_publish(room, kind, *args, **kwargs)

            state.extra_status["stimulus_fault"] = fault
            try:
                with (
                    patch.object(combat_init, "publish_game_event", filtered_publish)
                    if fault == "drop-gameplay"
                    else nullcontext()
                ):
                    await flow.run()
            except AssertionError as exc:
                expected_guard = {
                    "deactivate-session": "missing separate authenticated turn 2 and gameplay receipt",
                    "drop-gameplay": "missing Choir gameplay delivery: combat_started",
                    "bypass-receiver": "native receiver did not apply combat",
                    "skip-encounter": "missing named Choir encounter checkpoint",
                    "withhold-microphone": "missing separate authenticated turn 1 and gameplay receipt",
                    "dm-tone-only": "missing separate authenticated turn 1 and gameplay receipt",
                    "unrelated-burst": "missing separate authenticated turn 1 and gameplay receipt",
                }.get(fault)
                assert expected_guard is not None and str(exc) == expected_guard, (
                    f"wrong native fault diagnostic: {exc}"
                )
                if fault in ("withhold-microphone", "dm-tone-only", "unrelated-burst"):
                    assert not speech.source_receipts and not diagnostic.model.receipts
                else:
                    assert len(speech.source_receipts) == len(diagnostic.model.receipts) == 1
                    assert (
                        diagnostic.sd.combat_state is not None
                        and diagnostic.sd.combat_state.choir_encounter is not None
                    )
                    assert diagnostic.sd.combat_state.choir_encounter["phase"] == "search"
                assert frames >= 5
                fault_failure = str(exc)
                state.extra_status["choir_guard"] = fault
            else:
                assert fault == "none", "native fault did not red"
                assert len(speech.source_receipts) == len(diagnostic.model.receipts) > 2, (
                    "missing owned acoustic source"
                )
            state.extra_status["choir_complete"] = True
            return frames
    finally:
        try:
            evidence_path.write_text(
                json.dumps(
                    {
                        "microphone_frames": frames,
                        "status": state.extra_status,
                        "fault": fault,
                        "fault_failure": fault_failure,
                        "checkpoints": flow.checkpoints if flow is not None else {},
                        "native_checkpoints": native_checkpoints,
                        "acoustic_sources": speech.source_receipts,
                        "acoustic_diagnostic": [
                            {
                                "symbols": source.observed_symbols,
                                "max_purity": source.max_purity,
                                "sample_rates": sorted(source.sample_rates),
                            }
                            for source in speech.sources
                        ],
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
                for task in (monitor, native_monitor):
                    if task is not None:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
            finally:
                try:
                    combat_id = diagnostic.sd.combat_state.combat_id if diagnostic.sd.combat_state is not None else None
                    await diagnostic.aclose()
                    assert await db_queries.get_player(identity) is None, "owned Choir player survived cleanup"
                    if combat_id is not None:
                        assert await db_mutations.load_combat_state(combat_id) is None, (
                            "owned Choir combat survived cleanup"
                        )
                    evidence_path.with_name("cleanup.json").write_text(
                        json.dumps({"player_removed": True, "combat_removed": True}) + "\n"
                    )
                finally:
                    if manager is not None:
                        await manager.aclose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fault", choices=("none",), default="none")
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument(
        "--choir-fault",
        default="none",
        choices=(
            "none",
            "deactivate-session",
            "drop-gameplay",
            "bypass-receiver",
            "skip-encounter",
            "withhold-microphone",
            "dm-tone-only",
            "unrelated-burst",
        ),
    )
    args = parser.parse_args()

    async def exercise():
        async def receiver(room, identity, state):
            return await receive_commands(
                room, identity, state, args.result.with_name("microphone-turns.json"), args.choir_fault
            )

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
