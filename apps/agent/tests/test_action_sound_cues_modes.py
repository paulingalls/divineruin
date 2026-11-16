import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_mock_room, published_events, published_payloads

import event_types as E
from activity_tools import _begin_activity_impl
from creation_tools import finalize_character
from mode_tools import _enter_mode_impl
from onboarding_tools import advance_onboarding_beat
from session_data import CompanionState, CreationState

CASES = {
    "blacksmith": "action_enter_mode_blacksmith",
    "dispatch": "action_enter_mode_dispatch",
    "creation": "action_finalize_character",
}


def context():
    room = make_mock_room()
    room.isconnected.return_value = True
    ctx = make_context(room=room)
    ctx.userdata.event_bus.publish = MagicMock(wraps=ctx.userdata.event_bus.publish)
    return ctx


def cues(ctx):
    return [event.payload["sound_name"] for event in published_events(ctx) if event.event_type == E.PLAY_SOUND]


def assert_cue(ctx, sound_id):
    assert cues(ctx) == [sound_id]
    assert [p for p in published_payloads(ctx.userdata.room) if p["type"] == E.PLAY_SOUND] == [
        {"type": E.PLAY_SOUND, "sound_name": sound_id}
    ]


def watch_cue(ctx, log):
    original = ctx.userdata.event_bus.publish

    def record(event):
        if event.event_type == E.PLAY_SOUND:
            log.append("cue")
        return original(event)

    ctx.userdata.event_bus.publish = MagicMock(side_effect=record)


@pytest.mark.parametrize("mode", ["blacksmith", "dispatch"])
async def test_mode_cue_after_real_handoff(mode):
    ctx = context()
    ctx.session.current_agent = MagicMock(_agent_type="city")
    log = []
    watch_cue(ctx, log)
    module = f"{mode}_agent"
    factory = f"create_{mode}_agent"
    if mode == "dispatch":
        from dispatch_agent import create_dispatch_agent as real_factory
    else:
        from blacksmith_agent import create_blacksmith_agent as real_factory

    def create(**kwargs):
        assert getattr(ctx.userdata, f"pre_{mode}_agent_type") == "city"
        agent = real_factory(**kwargs)
        log.append("agent")
        return agent

    with patch(f"{module}.{factory}", side_effect=create):
        agent, response = await _enter_mode_impl(ctx, mode)
        log.append("return")
    assert agent is not None
    assert json.loads(response) == {"status": f"entered_{mode}"}
    assert getattr(ctx.userdata, f"pre_{mode}_agent_type") == "city"
    assert_cue(ctx, CASES[mode])
    assert log == ["agent", "cue", "return"]


@pytest.mark.parametrize("mode", ["blacksmith", "dispatch"])
async def test_mode_constructor_failure_has_no_cue(mode):
    ctx = context()
    ctx.session.current_agent = MagicMock(_agent_type="city")
    with patch(f"{mode}_agent.create_{mode}_agent", side_effect=RuntimeError("agent failed")) as constructor:
        with pytest.raises(RuntimeError, match="agent failed"):
            await _enter_mode_impl(ctx, mode)
    constructor.assert_called_once()
    assert cues(ctx) == []


@pytest.fixture
def meeting():
    with (
        patch(
            "onboarding_tools.db_queries.get_player",
            new_callable=AsyncMock,
            return_value={"class": "warrior", "level": 1},
        ),
        patch(
            "companion_relationship_queries.hydrate_assigned_companion_state",
            new_callable=AsyncMock,
            return_value=CompanionState(id="companion_lira", name="Lira"),
        ),
    ):
        yield


@pytest.mark.parametrize("beat", [1, 3])
async def test_onboarding_failure_has_no_cue(beat, meeting):
    ctx = context()
    ctx.userdata.onboarding_beat = beat

    async def persist(_player_id, flag, _value):
        if flag == "onboarding_beat":
            raise RuntimeError("write failed")

    with patch("onboarding_tools.db_mutations.set_player_flag", side_effect=persist):
        with pytest.raises(RuntimeError, match="write failed"):
            await advance_onboarding_beat._func(ctx)
    assert cues(ctx) == []


async def test_completed_onboarding_agent_failure_has_no_cue(meeting):
    ctx = context()
    ctx.userdata.onboarding_beat = 3
    with (
        patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock) as write,
        patch("gameplay_agent.create_gameplay_agent", side_effect=RuntimeError("agent failed")) as factory,
    ):
        with pytest.raises(RuntimeError, match="agent failed"):
            await advance_onboarding_beat._func(ctx)
    write.assert_any_await(ctx.userdata.player_id, "onboarding_beat", "complete")
    factory.assert_called_once()
    assert cues(ctx) == []


async def test_completed_onboarding_cue_failure_preserves_handoff(meeting):
    ctx = context()
    ctx.userdata.onboarding_beat = 3
    with (
        patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock) as write,
        patch.object(
            ctx.userdata.room.local_participant, "publish_data", side_effect=RuntimeError("cue failed")
        ) as publish,
    ):
        result = await advance_onboarding_beat._func(ctx)
    assert isinstance(result, tuple)
    assert json.loads(result[1])["onboarding_complete"] is True
    assert ctx.userdata.onboarding_beat is None
    write.assert_any_await(ctx.userdata.player_id, "onboarding_beat", "complete")
    publish.assert_awaited_once()


async def test_intermediate_onboarding_cue_failure_preserves_advanced_beat():
    ctx = context()
    ctx.userdata.onboarding_beat = 1
    with (
        patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock) as write,
        patch.object(
            ctx.userdata.room.local_participant, "publish_data", side_effect=RuntimeError("cue failed")
        ) as publish,
    ):
        result = await advance_onboarding_beat._func(ctx)
    assert isinstance(result, str)
    assert json.loads(result) == {"beat": 2, "beat_name": "market"}
    assert ctx.userdata.onboarding_beat == 2
    write.assert_awaited_once_with(ctx.userdata.player_id, "onboarding_beat", 2)
    publish.assert_awaited_once()


def creation_context():
    ctx = context()
    ctx.userdata.creation_state = CreationState(
        phase="identity", race="human", class_choice="mage", deity=None, name="Aric", backstory="Seeker."
    )
    return ctx


async def run_creation(ctx, failure=None):
    log = []
    watch_cue(ctx, log)

    async def player(*args):
        log.append("player")
        if failure == "player":
            raise RuntimeError("player failed")

    async def spell(*args, **kwargs):
        log.append("spell")
        if failure == f"spell_{log.count('spell')}":
            raise RuntimeError("spell failed")

    async def companion(*args):
        log.append("companion")
        if failure == "companion":
            raise RuntimeError("companion failed")

    async def payload(*args):
        log.append("payload")
        if failure == "payload":
            raise RuntimeError("payload failed")
        return {"character": {"name": "Aric"}}

    original_publish = ctx.userdata.room.local_participant.publish_data

    async def publish(data, **kwargs):
        kind = json.loads(data)["type"]
        log.append(kind)
        if failure == "session_init" and kind == E.SESSION_INIT:
            raise RuntimeError("session init failed")
        if failure == "cue_publish" and kind == E.PLAY_SOUND:
            raise RuntimeError("cue failed")
        return await original_publish(data, **kwargs)

    with (
        patch("creation_tools.db_mutations.create_player", side_effect=player),
        patch("creation_tools.character_spells.record_learned", side_effect=spell),
        patch("creation_tools.db_mutations_companion.insert_companion_relationship_if_absent", side_effect=companion),
        patch("creation_tools.db_session_queries.get_session_init_payload", side_effect=payload),
        patch.object(ctx.userdata.room.local_participant, "publish_data", side_effect=publish),
    ):
        if failure == "player":
            with pytest.raises(ToolError):
                await finalize_character._func(ctx)
            result = None
        else:
            result = await finalize_character._func(ctx)
            log.append("return")
    return result, log


async def test_creation_cue_after_all_steps():
    ctx = creation_context()
    result, log = await run_creation(ctx)
    assert isinstance(result, tuple)
    assert json.loads(result[1])["character"]["name"] == "Aric"
    assert log.count("spell") == 2
    assert log.index("player") < log.index("spell") < log.index("companion") < log.index("payload")
    assert (
        log.index("payload")
        < log.index(E.SESSION_INIT)
        < log.index("cue")
        < log.index(E.PLAY_SOUND)
        < log.index("return")
    )
    assert_cue(ctx, CASES["creation"])


@pytest.mark.parametrize("failure", ["player", "spell_1", "spell_2", "companion", "payload", "session_init"])
async def test_creation_prerequisite_failure_has_no_cue(failure):
    ctx = creation_context()
    result, log = await run_creation(ctx, failure)
    assert failure == "player" or isinstance(result, tuple)
    reached = "spell" if failure.startswith("spell") else E.SESSION_INIT if failure == "session_init" else failure
    assert reached in log
    assert cues(ctx) == []


async def test_creation_cue_publish_failure_preserves_handoff():
    ctx = creation_context()
    result, log = await run_creation(ctx, "cue_publish")
    assert isinstance(result, tuple)
    assert json.loads(result[1])["character"]["name"] == "Aric"
    assert ctx.userdata.creation_state.phase == "complete"
    assert ctx.userdata.onboarding_beat == 1
    assert E.SESSION_INIT in log
    assert E.PLAY_SOUND in log
    assert log[-1] == "return"


async def test_training_begin_cue_failure_preserves_committed_cycle():
    from test_training_initiate import SAMPLE_PROGRAM, _make_cycle

    import training_tools

    ctx = context()
    conn = object()
    committed = []

    @asynccontextmanager
    async def transaction():
        yield conn
        committed.append(True)

    db = MagicMock()
    db.transaction = transaction
    training = MagicMock(get_player_active_training_activities=AsyncMock(return_value=[]))

    async def create(*_args, **kwargs):
        assert kwargs["conn"] is conn
        return "t1"

    training.create_training_activity = AsyncMock(side_effect=create)
    real_training = partial(
        training_tools._initiate_training_cycle_impl,
        db_mod=db,
        db_training_mod=training,
        db_content_mod=MagicMock(get_training_program=AsyncMock(return_value=SAMPLE_PROGRAM)),
        rules_mod=lambda *_: _make_cycle(),
        now_fn=lambda: datetime(2026, 5, 22, tzinfo=UTC),
    )
    with patch.object(
        ctx.userdata.room.local_participant, "publish_data", side_effect=RuntimeError("cue failed")
    ) as publish:
        result = await _begin_activity_impl(
            ctx,
            "training",
            program_id="combat_basics",
            training_mod=MagicMock(_initiate_training_cycle_impl=real_training),
        )
    assert json.loads(result)["activity_id"] == "t1"
    training.create_training_activity.assert_awaited_once()
    assert committed == [True]
    publish.assert_awaited_once()


async def test_creation_agent_construction_failure_has_no_cue():
    ctx = creation_context()
    with patch("onboarding_agent.OnboardingAgent", side_effect=RuntimeError("agent failed")) as factory:
        with pytest.raises(RuntimeError, match="agent failed"):
            await run_creation(ctx)
    factory.assert_called_once()
    assert cues(ctx) == []
