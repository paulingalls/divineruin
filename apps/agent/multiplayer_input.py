import asyncio
import logging
from collections.abc import Callable
from typing import Any

from livekit.agents import stt

from multiplayer_transcription import TranscriptionFailure
from speech_delivery import deliver_player_turn

logger = logging.getLogger("divineruin.dm")


class MultiplayerInput:
    def __init__(
        self,
        transcriber: Any,
        lifecycle: Any,
        session: Any,
        userdata: Any,
        observe_player_speech: Callable[[tuple[stt.SpeechEvent, ...], str, str], None] | None = None,
    ) -> None:
        self.transcriber = transcriber
        self.lifecycle = lifecycle
        self.session = session
        self.userdata = userdata
        self.observe_player_speech = observe_player_speech
        self._task: asyncio.Task[None] | None = None

    def start(self) -> asyncio.Task[None]:
        if self._task is None:
            self._task = asyncio.create_task(self._run())
        return self._task

    async def _run(self) -> None:
        while True:
            try:
                transcript = await self.transcriber.receive()
            except TranscriptionFailure as exc:
                logger.error("Skipping failed player transcription: %s", exc)
                continue
            if not self.lifecycle.is_authorized(transcript.participant_identity, transcript.generation):
                logger.warning(
                    "Rejected transcript from %r at generation %s",
                    transcript.participant_identity,
                    transcript.generation,
                )
                continue
            identity = transcript.participant_identity
            generation = transcript.generation
            with self.userdata._bind_authenticated_actor(identity, generation, self.lifecycle.require_authorized):
                if self.observe_player_speech is not None:
                    if not transcript.speech_events:
                        raise RuntimeError(f"authenticated transcript from {identity!r} lost its STT event")
                    self.observe_player_speech(transcript.speech_events, identity, transcript.text)
                # speech_delivery owns the generate_reply boundary, including the two
                # RuntimeErrors a closing session raises — a turn in flight when the DM
                # session closes must not take the whole consumer down with it.
                await deliver_player_turn(
                    self.session,
                    transcript.text,
                    logger,
                    f"DM turn for {identity!r}",
                    revoked=lambda identity=identity, generation=generation: self.lifecycle.wait_until_revoked(
                        identity, generation
                    ),
                )

    async def aclose(self) -> None:
        task = self._task
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
