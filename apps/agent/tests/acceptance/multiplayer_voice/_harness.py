from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from acceptance._livekit_client import (
    aclose_audio,
    aclose_room,
    connect_room,
    create_microphone_track,
    load_pcm_wav,
    mint_access_token,
    play_audio_frames,
    set_audio_muted,
    unpublish_audio,
    wait_for_peer,
)
from livekit import rtc
from livekit.agents import utils
from livekit.plugins import deepgram

from multiplayer_transcription import AuthenticatedTranscript, MultiParticipantTranscriber


async def _authorize_transcription_fixture(_identity: str) -> int:
    return 1


@dataclass(frozen=True)
class SpeechFixture:
    filename: str
    utterance_id: str
    transcript: str
    sha256: str

    def spoken_in(self, text: str) -> bool:
        """Is `text` a transcript of THIS recording, heard from a real STT that drops words?"""
        return word_overlap(text, self.transcript) >= RECOGNIZED_OVERLAP

    @property
    def path(self) -> Path:
        return Path(__file__).parents[1] / "fixtures" / self.filename

    def frames(self) -> list[rtc.AudioFrame]:
        return load_pcm_wav(
            self.path,
            sha256=self.sha256,
            sample_rate=16000,
            channels=1,
            sample_width=2,
        )


@dataclass(frozen=True)
class PlayTrace:
    identity: str
    frame_seconds: float
    started_at: float
    speech_end: float


# Source mirror revision: https://huggingface.co/datasets/hf-internal-testing/librispeech_asr_dummy/tree/5be91486e11a2d616f4ec5db8d3fd248585ac07a
# Upstream corpus: https://huggingface.co/datasets/openslr/librispeech_asr, clean validation split.
# License: CC BY 4.0. Both recordings are LibriSpeech speaker 1272, chapter 128104.
# One-time conversion: ffmpeg -i <utterance>.flac -ac 1 -ar 16000 -c:a pcm_s16le <fixture>.wav
PLAYER_ONE_SPEECH = SpeechFixture(
    filename="player_one_voice.wav",
    utterance_id="1272-128104-0000",
    transcript="MISTER QUILTER IS THE APOSTLE OF THE MIDDLE CLASSES AND WE ARE GLAD TO WELCOME HIS GOSPEL",
    sha256="e846f8c9b1db13c8fa159b146cb6d797ee1861996d10b1dd3c387289ef5efd46",
)
PLAYER_TWO_SPEECH = SpeechFixture(
    filename="player_two_voice.wav",
    utterance_id="1272-128104-0001",
    transcript="NOR IS MISTER QUILTER'S MANNER LESS INTERESTING THAN HIS MATTER",
    sha256="9b231162963f0f9c22b9c4d985b3e657d1445aaa231ae33b663cea14e3972d64",
)


def normalized(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def word_overlap(actual: str, expected: str) -> float:
    """Share of `expected`'s distinct words that `actual` carries."""
    expected_words = set(normalized(expected).split())
    assert expected_words
    return len(set(normalized(actual).split()) & expected_words) / len(expected_words)


# Deepgram drops words: a full-gate run returned this speaker's whole sentence with only
# "apostle" missing, and a match on that one chosen token read it as no transcript at all.
# REJECTED: swapping in another literal — every remaining token is the same coin flip. So a
# recording is recognized by the SHARE of it that came back. Measured on these two fixtures:
# one dropped word scores 0.91-0.94, the OTHER fixture's speech 0.25-0.36, silence 0.0.
RECOGNIZED_OVERLAP = 0.75


class MultiplayerVoiceHarness:
    def __init__(self, server: dict[str, str]):
        suffix = uuid.uuid4().hex[:10]
        self.server = server
        self.room_name = f"multiplayer-transcription-{suffix}"
        self.player_one_identity = f"player-one-{suffix}"
        self.player_two_identity = f"player-two-{suffix}"
        self.player_one: rtc.Room | None = None
        self.player_two: rtc.Room | None = None
        self.listener: rtc.Room | None = None
        self.manager: MultiParticipantTranscriber | None = None
        self.audio: dict[str, tuple[rtc.AudioSource, rtc.LocalAudioTrack, rtc.LocalTrackPublication]] = {}
        self._http_context = None

    def _token(self, identity: str) -> str:
        return mint_access_token(
            api_key=self.server["api_key"],
            api_secret=self.server["api_secret"],
            room_name=self.room_name,
            identity=identity,
        )

    async def start(
        self,
        prepare_listener: Callable[[rtc.Room], Awaitable[Callable[[str], Awaitable[int | None]]]] | None = None,
        *,
        transcribe: bool = True,
    ) -> None:
        self._http_context = utils.http_context.open()
        await self._http_context.__aenter__()
        self.player_one = await connect_room(self.server["ws_url"], self._token(self.player_one_identity))
        if transcribe:
            self.audio[self.player_one_identity] = await create_microphone_track(
                self.player_one, sample_rate=16000, channels=1, name="player-one-microphone"
            )
        self.listener = await connect_room(self.server["ws_url"], self._token(f"transcriber-{uuid.uuid4().hex[:8]}"))
        await wait_for_peer(self.listener, identity=self.player_one_identity)
        authorizer = await prepare_listener(self.listener) if prepare_listener else _authorize_transcription_fixture
        if transcribe:
            stt = deepgram.STT(model="nova-3", language="en-US", endpointing_ms=300)
            self.manager = MultiParticipantTranscriber(self.listener, stt=stt, authorizer=authorizer)
            self.manager.start()
        self.player_two = await connect_room(self.server["ws_url"], self._token(self.player_two_identity))
        if transcribe:
            self.audio[self.player_two_identity] = await create_microphone_track(
                self.player_two, sample_rate=16000, channels=1, name="player-two-microphone"
            )
        await wait_for_peer(self.listener, identity=self.player_two_identity)
        if transcribe:
            await self.wait_for_active({self.player_one_identity, self.player_two_identity})
            await self.wait_for_microphone(self.player_one_identity, muted=False)
            await self.wait_for_microphone(self.player_two_identity, muted=False)

    async def wait_for_microphone(self, identity: str, *, muted: bool | None = None, published: bool = True) -> None:
        assert self.listener is not None
        async with asyncio.timeout(10):
            while True:
                participant = self.listener.remote_participants.get(identity)
                publications = (
                    [
                        publication
                        for publication in participant.track_publications.values()
                        if publication.kind == rtc.TrackKind.KIND_AUDIO
                    ]
                    if participant is not None
                    else []
                )
                if not published and not publications:
                    return
                if published and len(publications) == 1:
                    publication = publications[0]
                    if publication.track is not None and (muted is None or publication.muted is muted):
                        return
                await asyncio.sleep(0.02)

    async def wait_for_active(self, expected: set[str], timeout: float = 10) -> None:
        assert self.manager is not None
        try:
            async with asyncio.timeout(timeout):
                while self.manager.active_identities != expected:
                    await asyncio.sleep(0.02)
        except TimeoutError as exc:
            raise TimeoutError(
                f"transcriber sessions did not start: expected={sorted(expected)}, "
                f"active={sorted(self.manager.active_identities)}, "
                f"starting={sorted(self.manager._starting)}, failures={[str(e) for e in self.manager._failures]}"
            ) from exc

    async def play(self, identity: str, fixture: SpeechFixture) -> PlayTrace:
        frames = fixture.frames()
        frame_seconds = sum(frame.samples_per_channel / frame.sample_rate for frame in frames)
        started_at = asyncio.get_running_loop().time()
        await play_audio_frames(self.audio[identity][0], frames)
        return PlayTrace(identity, frame_seconds, started_at, asyncio.get_running_loop().time())

    async def mute(self, identity: str, muted: bool) -> None:
        set_audio_muted(self.audio[identity][1], muted)
        await self.wait_for_microphone(identity, muted=muted)

    async def unpublish(self, identity: str) -> None:
        room = self.player_one if identity == self.player_one_identity else self.player_two
        assert room is not None
        source, _track, publication = self.audio.pop(identity)
        await unpublish_audio(room, source, publication)
        await self.wait_for_microphone(identity, published=False)

    async def republish(self, identity: str) -> None:
        room = self.player_one if identity == self.player_one_identity else self.player_two
        assert room is not None
        self.audio[identity] = await create_microphone_track(
            room, sample_rate=16000, channels=1, name=f"{identity}-replacement-microphone"
        )
        await self.wait_for_microphone(identity, muted=False)

    async def disconnect_player_two(self) -> None:
        assert self.player_two is not None
        source, _track, _publication = self.audio.pop(self.player_two_identity)
        await aclose_audio(source)
        await aclose_room(self.player_two)
        self.player_two = None
        await self.wait_for_active({self.player_one_identity})
        async with asyncio.timeout(10):
            while self.manager is not None and self.manager._closing:
                await asyncio.sleep(0.02)
        await self.wait_for_microphone(self.player_one_identity, muted=False)

    async def reconnect_player_two(self) -> None:
        self.player_two = await connect_room(self.server["ws_url"], self._token(self.player_two_identity))
        await self.republish(self.player_two_identity)
        assert self.listener is not None
        await wait_for_peer(self.listener, identity=self.player_two_identity)
        await self.wait_for_active({self.player_one_identity, self.player_two_identity})

    async def receive(self, timeout: float = 20) -> AuthenticatedTranscript:
        assert self.manager is not None
        return await asyncio.wait_for(self.manager.receive(), timeout)

    async def await_speech(self, identity: str, fixture: SpeechFixture, timeout: float = 20) -> AuthenticatedTranscript:
        seen: list[AuthenticatedTranscript] = []
        fragments: list[str] = []
        generation: int | None = None
        try:
            async with asyncio.timeout(timeout):
                while True:
                    transcript = await self.receive(timeout)
                    seen.append(transcript)
                    if transcript.participant_identity != identity:
                        continue
                    if transcript.generation != generation:
                        fragments = []
                        generation = transcript.generation
                    fragments.append(transcript.text)
                    combined = " ".join(fragments)
                    if fixture.spoken_in(combined):
                        return AuthenticatedTranscript(identity, combined, transcript.generation)
        except TimeoutError as exc:
            active = sorted(self.manager.active_identities) if self.manager is not None else []
            raise TimeoutError(
                f"no {fixture.utterance_id} transcript for {identity!r}; active={active}, seen={seen}"
            ) from exc

    async def drain(self) -> list[AuthenticatedTranscript]:
        assert self.manager is not None
        drained = []
        while not self.manager._queue.empty():
            drained.append(await self.manager.receive())
        return drained

    async def assert_no_transcript(self, identity: str, duration: float = 3) -> None:
        deadline = asyncio.get_running_loop().time() + duration
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return
            try:
                transcript = await self.receive(remaining)
            except TimeoutError:
                return
            if transcript.participant_identity == identity:
                raise AssertionError(f"unexpected transcript from {identity!r}: {transcript.text!r}")

    async def aclose(self) -> None:
        failure = None
        try:
            if self.manager is not None:
                await self.manager.aclose()
        except BaseException as exc:
            failure = exc
        finally:
            for source, _track, _publication in tuple(self.audio.values()):
                await aclose_audio(source)
            for room in (self.player_two, self.listener, self.player_one):
                if room is not None:
                    await aclose_room(room)
            if self._http_context is not None:
                await self._http_context.__aexit__(None, None, None)
        if failure is not None:
            raise failure
