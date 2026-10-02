"""Fictional hearing/speech restrictions leave real microphone commands and DM receipts active."""

import asyncio
import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
from acceptance._livekit_client import register_data_packet_collector, wait_for_audio_track
from acceptance.multiplayer_voice._harness import PLAYER_TWO_SPEECH, MultiplayerVoiceHarness
from acceptance.multiplayer_voice.test_guest_leaves import ToneTTS
from acceptance.multiplayer_voice.test_host_handoff import LocalSTT
from acceptance.seeds import seed_player_with_pools
from acceptance.voice_condition_harness import ScenarioModel, assert_hud_floor, assert_receipt_floor
from livekit import rtc
from livekit.agents import AgentSession
from livekit.agents.testing import fake_job_context

import db
import db_mutations
import db_queries
from combat_agent import CombatAgent
from multiplayer_input import MultiplayerInput
from participant_lifecycle import PartyLifecycle, _setup_party_join
from session_data import CombatParticipant, CombatState, SessionData
from session_startup import GameplayInputOwner, gameplay_room_options

CASES = ("deafened_sight", "silenced_cast", "silenced_legal", "outside_cast", "guest_sight")


def scene(host, guest, case):
    actors = [
        CombatParticipant(id=pid, name=pid, type="player", initiative=15, hp_current=28, hp_max=28, ac=15)
        for pid in (host, guest)
    ]
    if case in ("deafened_sight", "guest_sight"):
        actors[1 if case == "guest_sight" else 0].conditions = [
            {"type": "deafened", "duration": 3, "source": "fixture"}
        ]
    positions = {host: {"x": 0, "y": 0, "z": 0}, guest: {"x": 50, "y": 0, "z": 0}}
    return CombatState(
        combat_id="voice-" + host,
        participants=actors,
        initiative_order=[host, guest],
        spatial={
            "positions": positions,
            "speeds": {host: 30, guest: 30},
            "locations": {"quiet_center": {"x": 0 if case.startswith("silenced") else 100, "y": 0, "z": 0}},
            "zones": {"quiet": {"kind": "silence", "center_id": "quiet_center", "radius_ft": 10}},
        },
    )


def commands(case, host):
    sight = (
        "check",
        {
            "roll": {
                "kind": "skill",
                "skill": "perception",
                "difficulty": "easy",
                "context_description": "look at the wall",
                "hearing_only": False,
            }
        },
    )
    save = ("check", {"roll": {"kind": "save", "save_type": "dexterity", "dc": 8, "effect_on_fail": "stumble"}})
    cast_spell = (
        "declare_phase",
        {
            "declarations": [
                {"kind": "ability", "actor_id": host, "action": "arcane_bolt", "targets": [], "argument_type": ""}
            ]
        },
    )
    if case == "silenced_cast":
        return [cast_spell, save]
    if case == "outside_cast":
        return [cast_spell, ("resolve_phase", {})]
    return [save] if case == "silenced_legal" else [sight]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES)
async def test_microphone_reaches_real_gameplay_verb_and_dm_receipt(case, livekit_server, reset_db_pool, monkeypatch):
    for key, field in (("LIVEKIT_URL", "ws_url"), ("LIVEKIT_API_KEY", "api_key"), ("LIVEKIT_API_SECRET", "api_secret")):
        monkeypatch.setenv(key, livekit_server[field])
    harness = MultiplayerVoiceHarness(livekit_server)
    host, guest = harness.player_one_identity, harness.player_two_identity
    pool = await db.get_pool()
    for pid in (host, guest):
        await seed_player_with_pools(
            pool, player_id=pid, class_="mage", focus_current=0 if case == "silenced_cast" else 10
        )
    sd = SessionData(player_id=host, location_id="accord_guild_hall")
    state = scene(host, guest, case)
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    sd.combat_state = await db_mutations.load_combat_state(state.combat_id)
    assert sd.combat_state is not None and sd.combat_state.spatial == state.spatial
    model = ScenarioModel(commands(case, host))
    session = AgentSession(llm=model, tts=ToneTTS(), max_tool_steps=5, userdata=sd)
    lifecycle: PartyLifecycle | None = None
    multiplayer = None
    stream: rtc.AudioStream | None = None
    audio_task = None
    received_audio = []
    transcripts = []
    events = asyncio.Queue()

    async def prepare(room):
        nonlocal lifecycle
        sd.room = room
        lifecycle = _setup_party_join(room, sd)
        sd.multiplayer_owner = cast(GameplayInputOwner, SimpleNamespace(lifecycle=lifecycle))
        with fake_job_context(room=room):
            await session.start(room=room, agent=CombatAgent(), room_options=gameplay_room_options(sd))
        return lifecycle.authorize

    async def capture_audio():
        assert stream is not None
        async for event in stream:
            if max(abs(sample) for sample in event.frame.data) > 500:
                received_audio.append(event.frame.duration)

    with patch("base_agent._make_tts", return_value=ToneTTS()):
        try:
            await harness.start(prepare, transcribe=True, stt=LocalSTT())
            assert (
                lifecycle is not None
                and harness.manager is not None
                and harness.player_two is not None
                and harness.listener is not None
            )
            active_lifecycle = cast(PartyLifecycle, lifecycle)
            assert await active_lifecycle.authorize(guest) is not None
            register_data_packet_collector(harness.player_two, topic="game_events", queue=events)
            track = await wait_for_audio_track(harness.player_two, identity=harness.listener.local_participant.identity)
            stream = rtc.AudioStream(track)
            audio_task = asyncio.create_task(capture_audio())
            receive = harness.manager.receive

            async def record_receive():
                heard = await receive()
                transcripts.append(heard)
                return heard

            monkeypatch.setattr(harness.manager, "receive", record_receive)
            multiplayer = MultiplayerInput(harness.manager, active_lifecycle, session, sd)
            multiplayer.start()
            assert not model.calls, "gameplay command executed before microphone input"
            speaker = guest if case == "guest_sight" else host
            await harness.play(speaker, PLAYER_TWO_SPEECH)
            try:
                async with asyncio.timeout(25):
                    while not model.narrated or sum(received_audio) < 0.2:
                        await asyncio.sleep(0.02)
            except TimeoutError as error:
                raise AssertionError("microphone command produced no complete gameplay/DM/audio receipt") from error
            assert any(turn.participant_identity == speaker and turn.text == "continue second" for turn in transcripts)
            assert_receipt_floor(model)
            outputs = list(model.receipts.values())
            if case == "silenced_cast":
                refusal = next(output for output in outputs if output.name == "declare_phase")
                assert refusal.is_error and "silenced" in refusal.output
                assert "cannot speak" in model.narration
                assert sd.combat_state.pending_declarations == {}
                row = await db_queries.get_player(host)
                assert row is not None and row["focus"]["current"] == 0
            else:
                assert all(not output.is_error for output in outputs)
            if case == "guest_sight":
                assert (await db_queries.get_single_skill_advancement(guest, "perception"))["use_counter"] == 1
                assert (await db_queries.get_single_skill_advancement(host, "perception"))["use_counter"] == 0
            hud = []
            async with asyncio.timeout(5):
                if events.empty():
                    data, identity = await events.get()
                    assert identity == harness.listener.local_participant.identity
                    hud.append(json.loads(data))
            while not events.empty():
                data, identity = events.get_nowait()
                assert identity == harness.listener.local_participant.identity
                hud.append(json.loads(data))
            assert_hud_floor(hud)
        finally:
            if multiplayer is not None:
                await multiplayer.aclose()
            if audio_task is not None:
                audio_task.cancel()
                await asyncio.gather(audio_task, return_exceptions=True)
            if stream is not None:
                await stream.aclose()
            await session.aclose()
            if lifecycle is not None:
                await cast(PartyLifecycle, lifecycle).aclose()
            await harness.aclose()


def test_command_receipt_and_hud_floors_fault_loudly():
    from livekit.agents import llm

    model = ScenarioModel([("check", {})])
    model.calls = {"one": "check"}
    with pytest.raises(AssertionError, match="missing DM receipt"):
        assert_receipt_floor(model)
    model.receipts = {"one": llm.FunctionCallOutput(name="check", call_id="one", output="{}", is_error=False)}
    assert_receipt_floor(model)
    model.calls = {}
    with pytest.raises(AssertionError, match="missing executed command"):
        assert_receipt_floor(model)
    with pytest.raises(AssertionError, match="no received HUD"):
        assert_hud_floor([])
    for defect in ({"x": 1}, {"resonance": 10}):
        with pytest.raises(AssertionError):
            assert_hud_floor([{"type": "fixture", "data": defect}])


@pytest.mark.asyncio
async def test_charm_held_reload_and_failed_landing_preserve_committed_state(reset_db_pool, monkeypatch):
    import uuid
    from unittest.mock import AsyncMock, MagicMock

    from combat._helpers import _call, _ctx_at_resolution, _resolve_deps

    import combat_events
    import conditions

    suffix = uuid.uuid4().hex
    pid, eid = "charm-player-" + suffix, "charm-enemy-" + suffix
    pool = await db.get_pool()
    await seed_player_with_pools(pool, player_id=pid, class_="mage")
    await db_mutations.update_player_hp(pid, 25)
    ctx = _ctx_at_resolution(player_hp=25, enemy_hp=30, reaction_ids=("skirmisher_sidestep", "rogue_uncanny_dodge"))
    raw = json.dumps(ctx.userdata.combat_state.to_dict()).replace("player_1", pid).replace("goblin_scout_1", eid)
    state = CombatState.from_dict(json.loads(raw))
    state.combat_id = "held-charm-" + suffix
    state.participants[0].conditions = [{"type": "charmed", "source": eid, "duration": 3}]
    state.pending_declarations[pid] = {"type": "defend", "action": "defend"}
    ctx.userdata = SessionData(player_id=pid, location_id="accord_guild_hall")
    ctx.userdata.combat_state = state
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    deps: dict = _resolve_deps(damage=3)
    deps["mutations"] = db_mutations
    deps["db_mod"] = db
    deps["resonance_mutations"] = MagicMock(update_player_resonance=AsyncMock())
    for _ in range(3):
        await _call(ctx, deps)
    loaded = await db_mutations.load_combat_state(state.combat_id)
    assert loaded is not None
    ctx.userdata.combat_state = loaded
    before = loaded.to_dict()
    assert loaded.participants[0].hp_current == 25
    assert conditions.has_condition(loaded.participants[0].conditions, "charmed")
    save = db_mutations.save_combat_state

    async def fail_after_save(*args, **kwargs):
        await save(*args, **kwargs)
        raise RuntimeError("fault after held damage save")

    flush = AsyncMock()
    with monkeypatch.context() as fault:
        fault.setattr(db_mutations, "save_combat_state", fail_after_save)
        fault.setattr(combat_events.EventSink, "flush", flush)
        with pytest.raises(RuntimeError, match="fault after held damage save"):
            await _call(ctx, deps)
    flush.assert_not_awaited()
    assert ctx.userdata.combat_state is loaded
    assert loaded.to_dict() == before
    rolled_back = await db_mutations.load_combat_state(state.combat_id)
    assert rolled_back is not None and rolled_back.to_dict() == before
    row = await db_queries.get_player(pid)
    assert row is not None and row["hp"]["current"] == 25
    await _call(ctx, deps)
    committed = await db_mutations.load_combat_state(state.combat_id)
    assert committed is not None
    assert committed.participants[0].hp_current == 22
    assert not conditions.has_condition(committed.participants[0].conditions, "charmed")
    row = await db_queries.get_player(pid)
    assert row is not None and row["hp"]["current"] == 22


@pytest.mark.asyncio
@pytest.mark.parametrize("silenced", [True, False])
async def test_public_save_commits_spoken_die_eligibility_once(silenced, reset_db_pool, monkeypatch):
    import uuid
    from unittest.mock import AsyncMock

    from sample_fixtures import make_context

    from check_tools import _check_save_impl

    pid = "spoken-save-" + uuid.uuid4().hex
    pool = await db.get_pool()
    await seed_player_with_pools(pool, player_id=pid, class_="mage")
    state = scene(pid, "other", "silenced_legal" if silenced else "outside_cast")
    actor = state.participants[0]
    actor.conditions = [{"type": "inspired"}, {"type": "blessed"}]
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    ctx = make_context(player_id=pid)
    ctx.userdata.combat_state = state
    monkeypatch.setattr("check_tools.publish_game_event", AsyncMock())
    await _check_save_impl(ctx, "wisdom", 8, "stunned")
    expected = [{"type": "inspired"}] if silenced else []
    assert ctx.userdata.combat_state.participants[0].conditions == expected
    loaded = await db_mutations.load_combat_state(state.combat_id)
    assert loaded is not None and loaded.participants[0].conditions == expected
    if silenced:
        assert loaded.spatial is not None
        loaded.spatial["positions"][pid]["x"] = 40
        await db_mutations.save_combat_state(loaded.combat_id, loaded.to_dict())
        ctx.userdata.combat_state = loaded
        await _check_save_impl(ctx, "wisdom", 8, "stunned")
        assert ctx.userdata.combat_state.participants[0].conditions == []
    await _check_save_impl(ctx, "wisdom", 8, "stunned")
    assert ctx.userdata.combat_state.participants[0].conditions == []
