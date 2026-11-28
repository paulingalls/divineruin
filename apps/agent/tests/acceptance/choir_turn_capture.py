"""Failure-only recording for the Choir capstone's authenticated microphone turns."""

import asyncio
import inspect
import logging
import time
import traceback
from collections import deque
from contextlib import ExitStack
from dataclasses import dataclass, field
from io import StringIO
from typing import cast
from unittest.mock import patch

from livekit.agents import AgentSession, FunctionToolsExecutedEvent, UserInputTranscribedEvent, llm

from multiplayer_transcription import AuthenticatedTranscript, MultiParticipantTranscriber, _TranscriberAgent

STAGES = (
    "audio_published",
    "stt_final",
    "turn_committed",
    "gameplay_input",
    "model_call_started",
    "tool_call_issued",
    "tool_executed",
    "receipt_observed",
)


@dataclass
class Turn:
    ordinal: int
    tool: str
    started: float
    transcript_offset: int
    stages: dict[str, list[tuple[float, str]]] = field(default_factory=dict)

    def record(self, stage: str, details: str = "") -> None:
        self.stages.setdefault(stage, []).append((time.monotonic(), details))


class SDKTurnLog(logging.Filter):
    def __init__(self, original_level: int) -> None:
        super().__init__()
        self.original_level = original_level
        self.entries: deque[tuple[float, logging.LogRecord]] = deque(maxlen=256)
        self.evictions = 0

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.INFO:
            return record.levelno >= self.original_level
        if len(self.entries) == self.entries.maxlen:
            self.evictions += 1
        self.entries.append((time.monotonic(), record))
        return False

    def dump(self, out: StringIO, started: float) -> None:
        predates = bool(self.entries and self.entries[0][0] <= started)
        window = "turn's SDK window was evicted" if self.evictions and not predates else "window retained"
        print(
            f"\nSDK DEBUG ({len(self.entries)}/{self.entries.maxlen} records, "
            f"{self.evictions} evictions, oldest predates turn={predates}, {window})",
            file=out,
        )
        standard = vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
        for _, entry in self.entries:
            extra = {key: value for key, value in vars(entry).items() if key not in standard}
            print(
                f"  {entry.created:.3f} {entry.filename}:{entry.lineno} {entry.funcName} "
                f"{entry.getMessage()} args={entry.args!r} fields={extra!r}",
                file=out,
            )


class ChoirTurnCapture:
    def __init__(self, player: str, transcripts: list[AuthenticatedTranscript]) -> None:
        self.player = player
        self.transcripts = transcripts
        self.turns: dict[int, Turn] = {}
        self.current: Turn | None = None
        self.messages: dict[str, Turn] = {}
        self.calls: dict[str, Turn] = {}
        self.unassigned_input: list[tuple[float, str, str]] = []
        self.manager: MultiParticipantTranscriber | None = None
        self.cleanup = ExitStack()
        self.sdk: SDKTurnLog | None = None

    def attach(self, manager: MultiParticipantTranscriber, gameplay: AgentSession) -> None:
        self.manager = manager
        for identity, session in manager._active.items():
            self._observe_input(identity, session)

        gameplay.on("function_tools_executed", self._tools_executed)
        self.cleanup.callback(gameplay.off, "function_tools_executed", self._tools_executed)

        logger = logging.getLogger("livekit.agents")
        self.sdk = SDKTurnLog(logger.getEffectiveLevel())
        self.cleanup.callback(logger.setLevel, logger.level)
        logger.addFilter(self.sdk)
        self.cleanup.callback(logger.removeFilter, self.sdk)
        logger.setLevel(logging.DEBUG)

    def _observe_input(self, identity: str, session: AgentSession) -> None:
        agent = cast(_TranscriberAgent, session.current_agent)
        generation = agent.generation
        complete = agent.on_user_turn_completed

        def final(event: UserInputTranscribedEvent) -> None:
            if event.is_final:
                self._input("stt_final", identity, generation, event.transcript)

        async def committed(turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
            self._input("turn_committed", identity, generation, new_message.text_content)
            await complete(turn_ctx, new_message=new_message)

        session.on("user_input_transcribed", final)
        self.cleanup.callback(session.off, "user_input_transcribed", final)
        self.cleanup.enter_context(patch.object(agent, "on_user_turn_completed", committed))

    def begin(self, ordinal: int, tool: str) -> Turn:
        turn = Turn(ordinal, tool, time.monotonic(), len(self.transcripts))
        self.turns[ordinal] = turn
        self.current = turn
        return turn

    def _input(self, stage: str, identity: str, generation: int, text: str | None) -> None:
        details = f"{identity=} {generation=} {text=}"
        turn = self.current
        if turn is None or identity != self.player or "receipt_observed" in turn.stages:
            self.unassigned_input.append((time.monotonic(), stage, details))
            return
        if text != f"capstone turn {turn.ordinal}":
            details += " (unexpected text)"
        turn.record(stage, details)

    def model_started(self, context: llm.ChatContext) -> Turn | None:
        message = next(
            (item for item in reversed(context.items) if isinstance(item, llm.ChatMessage) and item.role == "user"),
            None,
        )
        if message is None:
            return None
        turn = self.messages.get(message.id)
        if turn is None:
            turn = self.current
            if turn is None or "receipt_observed" in turn.stages or len(self.transcripts) <= turn.transcript_offset:
                return None
            heard = self.transcripts[-1]
            if heard.participant_identity != self.player or heard.text != message.text_content:
                return None
            self.messages[message.id] = turn
        turn.record("model_call_started", f"message_id={message.id} text={message.text_content!r}")
        return turn

    def tool_issued(self, ordinal: int, call_id: str, name: str) -> None:
        turn = self.turns[ordinal]
        self.calls[call_id] = turn
        turn.record("tool_call_issued", f"{call_id=} {name=}")

    def _tools_executed(self, event: FunctionToolsExecutedEvent) -> None:
        for _call, output in event.zipped():
            self.output("tool_executed", output)

    def output(self, stage: str, output: llm.FunctionCallOutput) -> None:
        turn = self.calls.get(output.call_id)
        if turn is not None:
            turn.record(
                stage,
                f"call_id={output.call_id} name={output.name!r} is_error={output.is_error} "
                f"output_len={len(output.output)} output={output.output[:300]!r}",
            )

    def timeout_message(self, ordinal: int, headline: str) -> str:
        missing = self.turns[ordinal]
        turns = StringIO()
        last = "none"
        for i, turn in self.turns.items():
            reached = self._dump_turn(turns, turn, self.turns.get(i + 1))
            if i == ordinal:
                last = reached
        out = StringIO()
        print(
            f"{headline} (expected tool {missing.tool}, authenticated player {self.player}, last_stage={last})",
            file=out,
        )
        out.write(turns.getvalue())
        if self.unassigned_input:
            print(f"\nInput outside the expected player's pending turn: {self.unassigned_input!r}", file=out)
        manager = self.manager
        if manager is not None:
            print(
                f"\nTranscriber active_identities={sorted(manager.active_identities)} "
                f"start_counts={manager.start_counts!r} failures={manager._failures!r}",
                file=out,
            )
        if self.sdk is not None:
            self.sdk.dump(out, missing.started)
        print("\nPending asyncio tasks", file=out)
        for task in sorted(asyncio.all_tasks(), key=lambda task: task.get_name()):
            self._dump_task(out, task)
        return out.getvalue()

    @staticmethod
    def _dump_task(out: StringIO, task: asyncio.Task[object]) -> None:
        print(f"{task.get_name()} {task.get_coro()!r}", file=out)
        # Task.get_stack() shows only the outer frame of a suspended coroutine.
        awaited: object = task.get_coro()
        while inspect.iscoroutine(awaited) or inspect.isgenerator(awaited):
            if inspect.iscoroutine(awaited):
                frame, awaited = awaited.cr_frame, awaited.cr_await
            else:
                frame, awaited = awaited.gi_frame, awaited.gi_yieldfrom
            if frame is not None:
                traceback.print_stack(frame, limit=1, file=out)

    def _dump_turn(self, out: StringIO, turn: Turn, following: Turn | None) -> str:
        stop = following.transcript_offset if following is not None else len(self.transcripts)
        received = [
            f"identity={heard.participant_identity!r} generation={heard.generation} text={heard.text!r}"
            for heard in self.transcripts[turn.transcript_offset : stop]
            if heard.participant_identity == self.player
        ]
        reached = set(turn.stages)
        if received:
            reached.add("gameplay_input")
        last = next((stage for stage in reversed(STAGES) if stage in reached), "none")
        print(f"\nTurn {turn.ordinal} expected_tool={turn.tool} last_stage={last}", file=out)
        for stage in STAGES:
            if stage == "gameplay_input" and received:
                print(f"  {stage}: {', '.join(received)}", file=out)
            elif entries := turn.stages.get(stage):
                for observed, details in entries:
                    print(f"  {stage}: +{observed - turn.started:.3f}s {details}".rstrip(), file=out)
            else:
                suffix = " (STT text not observed)" if stage == "stt_final" else ""
                print(f"  {stage}: absent{suffix}", file=out)
        for observed, branch in turn.stages.get("model_branch", ()):
            print(f"  model_branch: +{observed - turn.started:.3f}s {branch}", file=out)
        return last

    def close(self) -> None:
        self.cleanup.close()
