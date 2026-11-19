import asyncio

from acceptance.choir_capstone_harness import ChoirEncounterDiagnostic

from multiplayer_transcription import AuthenticatedTranscript


class ChoirProbeTurns(ChoirEncounterDiagnostic):
    def __init__(self, player_id):
        super().__init__(player_id)
        self.queue: asyncio.Queue[AuthenticatedTranscript] = asyncio.Queue()
        self.submitted: list[str] = []

    async def receive(self) -> AuthenticatedTranscript:
        return await self.queue.get()

    async def command(self, name, arguments, play):
        assert self.lifecycle is not None
        count = len(self.model.commands) + 1
        generation = self.lifecycle.current_generation(self.player_id)
        assert generation is not None and generation > 0, "Choir probe has no live participant generation"
        self.lifecycle.require_authorized(self.player_id, generation)
        self.model.commands.append((name, arguments))
        await play()
        text = f"capstone turn {count}"
        self.submitted.append(text)
        await self.queue.put(AuthenticatedTranscript(self.player_id, text, generation))
        await self.wait_for_receipts(count)
        receipt = list(self.model.receipts.values())[-1]
        assert receipt.name == name and receipt.output.strip(), "missing public tool receipt"
        assert len(self.transcripts) == count, "command requires a separate authenticated probe turn"
        turn = self.transcripts[-1]
        assert turn.participant_identity == self.player_id and turn.generation == generation and turn.text == text
        assert not turn.speech_events, "Choir probe transcript unexpectedly carries STT evidence"
        return receipt
