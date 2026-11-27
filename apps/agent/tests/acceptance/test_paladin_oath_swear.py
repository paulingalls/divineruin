"""Spoken offers and registered choices persist the speaker's accepted oath."""

import asyncio
import json
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from _zhael_fate_fixtures import game_tools
from acceptance._livekit_client import wait_for_audio_track
from acceptance.choir_capstone_harness import ChoirEncounterDiagnostic
from acceptance.choir_capstone_voice import CHOIR_COMMAND_SPEECH, BurstStream, BurstSTT, TurnModel
from acceptance.multiplayer_voice._harness import MultiplayerVoiceHarness
from acceptance.multiplayer_voice.test_guest_leaves import ToneTTS
from acceptance.seeds import seed_player_with_pools
from acceptance.test_voice_condition_commands import scene
from livekit import rtc
from livekit.agents import AgentSession, ToolError, llm, stt
from livekit.agents.testing import fake_job_context
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from pydantic import ValidationError
from sample_fixtures import make_context

import db
import db_mutations
import db_queries
from combat_agent import CombatAgent
from participant_lifecycle import _setup_party_join
from session_data import SessionData
from session_startup import GameplayInputOwner, gameplay_room_options


@pytest.fixture
def mock_combat_agent_factory():
    return None


JUSTICE_TERMS = ["strike_first", "strike_surrendered_enemy", "strike_yielded_ally"]
HOST = "oath_host"
GUEST = "oath_guest"
FOE = "merchant_1"


async def patch_player(player_id: str, **fields) -> None:
    pool = await db.get_pool()
    await pool.execute("UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", player_id, json.dumps(fields))


async def seed_paladin(player_id: str, patron: str) -> None:
    await seed_player_with_pools(await db.get_pool(), player_id=player_id, class_="paladin")
    await patch_player(player_id, divine_favor={"patron": patron, "level": 0, "max": 100, "last_whisper_level": 0})


async def stored(player_id: str) -> dict | None:
    player = await db_queries.get_player(player_id)
    assert player is not None
    return player.get("oaths")


async def invoke(session: SessionData, tool_name: str, **payload) -> dict:
    call = game_tools(session, agent=CombatAgent())
    return await call(tool_name, **payload)


async def assert_refused(session: SessionData, reason: str, **selection) -> None:
    actor = session.acting_player_id
    before = await stored(actor)
    refusal = None
    accepted = None
    try:
        accepted = await invoke(session, "select", **selection)
    except ToolError as error:
        refusal = str(error)
    assert await stored(actor) == before
    assert accepted is None
    assert refusal is not None and reason in refusal


@pytest.fixture
async def fight(reset_db_pool):
    await seed_paladin(HOST, "zhael")
    await seed_paladin(GUEST, "zhael")
    ctx = make_context(HOST, party_member_ids=[GUEST])
    state = scene(HOST, GUEST, "outside_cast")
    state.combat_id = f"oath-fight-{uuid4().hex[:8]}"
    state.encounter_id = "reusable_encounter"
    state.round_number = 2
    state.participants[-1].tier = 1
    ctx.userdata.combat_state = state
    try:
        yield ctx.userdata
    finally:
        pool = await db.get_pool()
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)
        await pool.execute("DELETE FROM players WHERE player_id = ANY($1::text[])", [HOST, GUEST])


async def timed_offer(ctx: SessionData, *, origin: str | None = None) -> dict:
    combat = await invoke(ctx, "query_info", kind="combat", **({"target_id": origin} if origin else {}))
    offer = combat["oath_choice"]
    assert offer["options"] == ["timed"]
    assert offer["min_last_round"] == 2
    assert FOE in offer["eligible_targets"]["defeat_target"]
    return offer


def timed(offer: dict, *, objective: str = "defeat_target", target: str = FOE, deadline: int = 3) -> dict:
    return dict(
        choice_id=offer["choice_id"], option="timed", objective_kind=objective, target_id=target, last_round=deadline
    )


async def test_timed_oath_survives_checkpoint_and_concurrent_replay(fight):
    state = fight.combat_state
    offer = await timed_offer(fight)
    target = next(iter(offer["eligible_targets"]["defeat_target"]))
    selection = timed(offer, target=target)
    first, second = await asyncio.gather(invoke(fight, "select", **selection), invoke(fight, "select", **selection))
    assert first == second
    records = await stored(HOST)
    assert records is not None
    [record] = records["records"]
    assert record["id"] == first["oath_id"]
    assert record["latest_state_change_event_id"] == first["latest_state_change_event_id"]
    assert (record["kind"], record["status"], record["patron"], record["owner_id"]) == (
        "timed",
        "active",
        "zhael",
        HOST,
    )
    assert record["terms"] == first["terms"] == ["defeat_target"]
    assert (record["combat_id"], record["round_number"], record["last_round"]) == (state.combat_id, 2, 3)
    assert record["bound_entity_ids"] == [target] and record["target_id"] == target
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    reloaded = await db_mutations.load_combat_state(state.combat_id)
    assert reloaded is not None and reloaded is not state and reloaded.round_number == 2
    fight.combat_state = reloaded
    assert await invoke(fight, "select", **selection) == first
    for change in ({"target_id": GUEST}, {"objective_kind": "keep_ally_standing"}, {"last_round": 4}):
        await assert_refused(fight, "different selection", **(selection | change))
    next_id = selection["choice_id"].removesuffix("_0") + "_1"
    await assert_refused(fight, "active oath", **(selection | {"choice_id": next_id}))
    assert (await invoke(fight, "query_info", kind="combat"))["oath_choice"] is None
    assert await stored(HOST) == records


async def test_authenticated_guest_can_bind_a_standing_ally_in_the_current_round(fight):
    sd = fight
    with sd._bind_authenticated_actor(GUEST, 1, lambda _id, _generation: None):
        offer = await timed_offer(fight, origin=HOST)
        abilities = await invoke(fight, "query_info", kind="abilities")
        assert abilities["oath_choice"] == offer
        target = next(target for target in offer["eligible_targets"]["keep_ally_standing"] if target == HOST)
        selection = timed(offer, objective="keep_ally_standing", target=target, deadline=2)
        receipt = await invoke(fight, "select", **selection)
    blob = await stored(GUEST)
    assert blob is not None
    [record] = blob["records"]
    assert record["owner_id"] == GUEST and record["bound_entity_ids"] == [HOST]
    assert record["id"] == receipt["oath_id"] and record["last_round"] == record["round_number"] == 2
    assert record["terms"] == ["keep_ally_standing"]
    await assert_refused(fight, "choice ID", **selection)
    assert await stored(HOST) is None


@pytest.mark.parametrize(
    "changed, reason",
    [
        ("class", "paladin"),
        ("patron", "patron"),
        ("option", "option"),
        ("outside", "during combat"),
        ("encounter", "choice ID"),
        ("participant", "participating"),
        ("nonplayer_participant", "participating"),
        ("deadline", "current round"),
        ("defeated", "living hostile"),
        ("downed", "standing ally"),
        ("self_ally", "standing ally"),
        ("downed_speaker", "above 0 HP"),
        ("dead", "living hostile"),
        ("wrong_side_hostile", "standing ally"),
        ("wrong_side_ally", "living hostile"),
        ("structure", "living hostile"),
        ("unoffered_target", "living hostile"),
        ("unoffered_choice", "choice ID"),
    ],
)
async def test_locked_selection_rejects_unoffered_or_stale_facts(fight, changed, reason):
    offer = await timed_offer(fight)
    selection = timed(offer)
    state = fight.combat_state
    foe = state.get_participant(FOE)
    ally = state.get_participant(GUEST)
    assert foe is not None and ally is not None
    if changed == "class":
        await patch_player(HOST, **{"class": "warrior"})
    elif changed == "patron":
        await patch_player(HOST, divine_favor={"patron": "kaelen"})
    elif changed == "option":
        selection = {"choice_id": offer["choice_id"], "option": "justice"}
    elif changed == "outside":
        fight.combat_state = None
    elif changed == "encounter":
        state.combat_id += "-replacement"
    elif changed == "participant":
        state.participants = [actor for actor in state.participants if actor.id != HOST]
    elif changed == "nonplayer_participant":
        speaker = state.get_participant(HOST)
        assert speaker is not None
        speaker.type = "companion"
    elif changed == "deadline":
        selection["last_round"] = 1
    elif changed == "defeated":
        foe.hp_current = 0
    elif changed == "downed":
        ally.hp_current = 0
        selection = timed(offer, objective="keep_ally_standing", target=GUEST)
    elif changed == "self_ally":
        selection = timed(offer, objective="keep_ally_standing", target=HOST)
    elif changed == "downed_speaker":
        speaker = state.get_participant(HOST)
        assert speaker is not None
        speaker.hp_current = 0
    elif changed == "dead":
        foe.is_dead = True
    elif changed == "wrong_side_hostile":
        selection["objective_kind"] = "keep_ally_standing"
    elif changed == "wrong_side_ally":
        selection["target_id"] = GUEST
    elif changed == "structure":
        foe.type = "structure"
    elif changed == "unoffered_target":
        selection["target_id"] = "unknown_actor"
    elif changed == "unoffered_choice":
        selection["choice_id"] += "_unknown"
    await assert_refused(fight, reason, **selection)
    assert await stored(HOST) is None


@pytest.mark.parametrize("replay", [False, True])
async def test_revoked_speaker_cannot_resolve_oath_after_player_lock(fight, monkeypatch, replay):
    active = True
    get_locked = db_queries.get_players_for_update

    async def lock_then_revoke(*args, **kwargs):
        nonlocal active
        rows = await get_locked(*args, **kwargs)
        active = False
        return rows

    def validate(_actor: str, _generation: int) -> None:
        if not active:
            raise RuntimeError("Speaker revoked")

    with fight._bind_authenticated_actor(GUEST, 1, validate):
        selection = timed(await timed_offer(fight))
        if replay:
            await invoke(fight, "select", **selection)
        before = await stored(GUEST)
        monkeypatch.setattr(db_queries, "get_players_for_update", lock_then_revoke)
        refusal = None
        accepted = None
        try:
            accepted = await invoke(fight, "select", **selection)
        except RuntimeError as error:
            refusal = str(error)
    assert await stored(GUEST) == before
    assert accepted is None
    assert refusal == "Speaker revoked"


@pytest.mark.parametrize(
    "corrupt, error",
    [
        ("root_key", ValidationError),
        ("missing_field", ValidationError),
        ("wrong_owner", ValueError),
        ("duplicate_choice", ValueError),
        ("wrong_terms", ValidationError),
        ("wrong_binding", ValidationError),
        ("justice_terms", ValidationError),
        ("justice_binding", ValidationError),
    ],
)
async def test_oath_registry_refuses_malformed_player_data(fight, corrupt, error):
    if corrupt.startswith("justice_"):
        await patch_player(HOST, divine_favor={"patron": "valdris"})
        offer = (await invoke(fight, "query_info", kind="combat"))["oath_choice"]
        selection = {"choice_id": offer["choice_id"], "option": "justice"}
    else:
        selection = timed(await timed_offer(fight))
    await invoke(fight, "select", **selection)
    blob = await stored(HOST)
    assert blob is not None
    [record] = blob["records"]
    if corrupt == "root_key":
        blob["unknown"] = True
    elif corrupt == "missing_field":
        del record["patron"]
    elif corrupt == "wrong_owner":
        record["owner_id"] = GUEST
    elif corrupt == "duplicate_choice":
        blob["records"].append(record.copy())
    elif corrupt in ("wrong_terms", "justice_terms"):
        record["terms"] = ["keep_ally_standing"]
    elif corrupt in ("wrong_binding", "justice_binding"):
        record["bound_entity_ids"] = [GUEST]
    await patch_player(HOST, oaths=blob)
    receipt = None
    try:
        receipt = await invoke(fight, "select", **selection)
    except error:
        pass
    assert receipt is None
    assert await stored(HOST) == blob


async def test_valdris_oath_is_offered_and_read_back_over_voice(livekit_server, reset_db_pool):
    harness = MultiplayerVoiceHarness(livekit_server)
    diagnostic = JusticeDiagnostic(harness.player_one_identity)
    speech: asyncio.Queue[str] = asyncio.Queue()
    audio: rtc.AudioStream | None = None
    tasks: list[asyncio.Task] = []

    async def prepare(room):
        await seed_paladin(harness.player_two_identity, "valdris")
        await diagnostic.start(room)
        return diagnostic.lifecycle.authorize

    async def speak():
        await harness.play(harness.player_one_identity, CHOIR_COMMAND_SPEECH)

    async def heard_all(phrases: list[str]) -> None:
        received = ""
        async with asyncio.timeout(10):
            while not all(phrase in received for phrase in phrases):
                received += await speech.get()

    try:
        await harness.start(prepare, stt=JusticeSTT())
        assert harness.player_one is not None and harness.listener is not None
        agent_identity = harness.listener.local_participant.identity

        def receive(reader: rtc.TextStreamReader, identity: str) -> None:
            if identity != agent_identity:
                return

            async def read() -> None:
                speech.put_nowait(await reader.read_all())

            tasks.append(asyncio.create_task(read()))

        harness.player_one.register_text_stream_handler("lk.transcription", receive)
        diagnostic.attach(harness.manager)
        track = await wait_for_audio_track(harness.player_one, identity=agent_identity)
        audio = rtc.AudioStream(track)
        offer_result = await diagnostic.command("query_info", {"kind": "abilities"}, speak)
        assert not offer_result.is_error, offer_result.output
        offer = json.loads(offer_result.output)["oath_choice"]
        assert offer["options"] == ["justice"] and offer["name"] == "Oath of Justice"
        assert await stored(diagnostic.player_id) is None
        await heard_all([offer["name"], *offer["term_descriptions"]["justice"]])
        async with asyncio.timeout(5):
            frame = await anext(audio)
        assert frame.frame.samples_per_channel > 0
        receipt_result = await diagnostic.command(
            "select", {"choice_id": offer["choice_id"], "option": "justice"}, speak
        )
        assert diagnostic.transcripts[-1].text == "I swear the Oath of Justice."
        assert not receipt_result.is_error, receipt_result.output
        receipt = json.loads(receipt_result.output)
        assert receipt["terms"] == JUSTICE_TERMS
        await heard_all([receipt["oath_id"], *receipt["term_descriptions"]])
        blob = await stored(diagnostic.player_id)
        assert blob is not None
        [record] = blob["records"]
        assert record["id"] == receipt["oath_id"]
        assert record["terms"] == JUSTICE_TERMS
        assert (record["owner_id"], record["patron"], record["status"]) == (diagnostic.player_id, "valdris", "active")
        assert await invoke(diagnostic.sd, "select", choice_id=offer["choice_id"], option="justice") == receipt
        await assert_refused(diagnostic.sd, "different selection", choice_id=offer["choice_id"], option="valor")
        assert await stored(diagnostic.player_id) == blob
    finally:
        if audio is not None:
            await audio.aclose()
        await diagnostic.aclose()
        await harness.aclose()
        await asyncio.gather(*tasks, return_exceptions=True)
        pool = await db.get_pool()
        await pool.execute("DELETE FROM players WHERE player_id=$1", harness.player_two_identity)


class JusticeSpeech(BurstStream):
    async def __anext__(self) -> stt.SpeechEvent:
        event = await super().__anext__()
        if event.type == stt.SpeechEventType.FINAL_TRANSCRIPT:
            speech = event.alternatives[0]
            speech.text = {
                "capstone turn 1": "What oath can I swear?",
                "capstone turn 2": "I swear the Oath of Justice.",
            }[speech.text]
        return event


class JusticeSTT(BurstSTT):
    def stream(self, *, language="en", conn_options=DEFAULT_API_CONNECT_OPTIONS):
        return JusticeSpeech(stt=self, conn_options=conn_options)


class JusticeTurn(llm.LLMStream):
    async def _run(self) -> None:
        model = self._llm
        assert isinstance(model, JusticeModel)
        latest = None
        for item in self._chat_ctx.items:
            if isinstance(item, llm.FunctionCallOutput) and item.call_id in model.calls:
                model.receipts[item.call_id] = item
                latest = item
        if len(model.calls) < len(model.commands):
            name, payload = model.commands[len(model.calls)]
            utterance = next(
                item.text_content
                for item in reversed(self._chat_ctx.items)
                if isinstance(item, llm.ChatMessage) and item.role == "user"
            )
            assert utterance == ("I swear the Oath of Justice." if name == "select" else "What oath can I swear?")
            call_id = uuid4().hex
            model.calls[call_id] = name
            delta = llm.ChoiceDelta(
                role="assistant",
                tool_calls=[llm.FunctionToolCall(name=name, arguments=json.dumps(payload), call_id=call_id)],
            )
        else:
            assert latest is not None
            receipt = json.loads(latest.output) if not latest.is_error else {}
            if offer := receipt.get("oath_choice"):
                spoken = offer["name"] + ". " + " ".join(offer["term_descriptions"]["justice"]) + " Do you swear?"
            elif "oath_id" in receipt:
                spoken = f"Oath {receipt['oath_id']} is bound. " + " ".join(receipt["term_descriptions"])
            else:
                spoken = "There is no oath to read back."
            delta = llm.ChoiceDelta(role="assistant", content=spoken)
        self._event_ch.send_nowait(llm.ChatChunk(id=uuid4().hex, delta=delta))


class JusticeModel(TurnModel):
    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **_kwargs):
        return JusticeTurn(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class JusticeDiagnostic(ChoirEncounterDiagnostic):
    async def start(self, room):
        await seed_paladin(self.player_id, "valdris")
        self.model = JusticeModel([])
        self.sd = SessionData(player_id=self.player_id, location_id="accord_guild_hall")
        self.sd.room = room
        self.lifecycle = _setup_party_join(room, self.sd)
        self.sd.multiplayer_owner = cast(GameplayInputOwner, SimpleNamespace(lifecycle=self.lifecycle))
        self.session = AgentSession(llm=self.model, tts=ToneTTS(), max_tool_steps=5, userdata=self.sd)
        options = gameplay_room_options(self.sd)
        options.text_output = True
        self.tts_patch.start()
        with fake_job_context(room=room):
            await self.session.start(room=room, agent=CombatAgent(), room_options=options)
