import asyncio
import logging
from typing import Any

from multiplayer_transcription import TranscriptionFailure
from speech_delivery import deliver_player_turn

logger = logging.getLogger("divineruin.dm")


class MultiplayerInput:
    def __init__(self, transcriber: Any, lifecycle: Any, session: Any, userdata: Any) -> None:
        self.transcriber = transcriber
        self.lifecycle = lifecycle
        self.session = session
        self.userdata = userdata
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
            with self.userdata._bind_actor(transcript.participant_identity):
                # speech_delivery owns the generate_reply boundary, including the two
                # RuntimeErrors a closing session raises — a turn in flight when the DM
                # session closes must not take the whole consumer down with it.
                await deliver_player_turn(
                    self.session,
                    transcript.text,
                    logger,
                    f"DM turn for {transcript.participant_identity!r}",
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
