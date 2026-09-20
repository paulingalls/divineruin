from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import pytest
from acceptance._live_voice import has_live_voice_key
from acceptance.multiplayer_voice._harness import (
    PLAYER_ONE_SPEECH,
    PLAYER_TWO_SPEECH,
    MultiplayerVoiceHarness,
    normalized,
)
from acceptance.seeds import seed_player_with_pools
from livekit import rtc
from livekit.agents import Agent, AgentSession, llm
from livekit.agents.llm import ToolContext
from livekit.agents.testing import fake_job_context
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

import db
import db_mutations_concentration
import db_mutations_resonance
import db_queries
import reaction_spend
import reaction_windows
from activate_tools import activate
from multiplayer_input import MultiplayerInput
from participant_lifecycle import PartyLifecycle, _setup_party_join
from session_data import CombatParticipant, CombatState, SessionData
from session_startup import gameplay_room_options

# The skipif is the not-opted-in path (CI without the secret, a worktree carrying
# .env.example's placeholder); REQUIRE_REAL_LLM=1 suppresses it so the conftest fixture
# fails this lane LOUD rather than letting it absent itself from the boundary.
pytestmark = pytest.mark.skipif(
    not has_live_voice_key(os.environ) and not os.environ.get("REQUIRE_REAL_LLM"),
    reason="live-voice acceptance drives the real Deepgram STT API and needs DEEPGRAM_API_KEY",
)


class ActivateStream(llm.LLMStream):
    def __init__(self, model: ActivateModel, **kwargs: Any) -> None:
        super().__init__(model, **kwargs)
        self.model = model

    async def _run(self) -> None:
        last = self.chat_ctx.items[-1]
        request_id = uuid.uuid4().hex
        if isinstance(last, llm.ChatMessage) and last.role == "user":
            self.model.user_turns.append(last.text_content or "")
            call = llm.FunctionToolCall(
                name="activate",
                arguments='{"id":"guardian_intercept"}',
                call_id=f"activate-{request_id}",
            )
            delta = llm.ChoiceDelta(role="assistant", tool_calls=[call])
        else:
            self.model.completed_turns += 1
            delta = llm.ChoiceDelta(role="assistant", content="Reaction resolved.")
        self._event_ch.send_nowait(llm.ChatChunk(id=request_id, delta=delta))


class ActivateModel(llm.LLM):
    def __init__(self) -> None:
        super().__init__()
        self.user_turns: list[str] = []
        self.completed_turns = 0

    def chat(
        self,
        *,
        chat_ctx,
        tools=None,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
        **_kwargs,
    ) -> llm.LLMStream:
        return ActivateStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


def _combat(player_one: str, player_two: str) -> CombatState:
    players = [
        CombatParticipant(
            id=player_id,
            name=player_id,
            type="player",
            initiative=20 - index,
            hp_current=25,
            hp_max=25,
            ac=14,
            has_reaction_ability=True,
            reaction_ids=["guardian_intercept"],
        )
        for index, player_id in enumerate((player_one, player_two))
    ]
    enemy = CombatParticipant(
        id="goblin_scout_1",
        name="Goblin Scout",
        type="enemy",
        initiative=12,
        hp_current=7,
        hp_max=7,
        ac=13,
    )
    state = CombatState(
        combat_id=f"reaction-{uuid.uuid4().hex}",
        participants=[*players, enemy],
        initiative_order=[player_one, player_two, enemy.id],
        round_number=1,
        current_turn_index=2,
        location_id="accord_guild_hall",
        beat="narration",
    )
    state.held_actions = [
        {
            "seq": 3,
            "actor_id": enemy.id,
            "initiative": enemy.initiative,
            "declaration": {"type": "attack", "action": "Scimitar", "target_id": player_one},
            "roll": None,
            "opened": [reaction_windows.POST_ROLL],
        }
    ]
    state.open_window = reaction_windows.open_window_for(
        round_number=1,
        seq=3,
        stage=reaction_windows.POST_ROLL,
        actor_id=enemy.id,
        target_id=player_one,
        action_kind="attack",
        triggers=reaction_windows.post_roll_triggers({}, hit=True),
    )
    state.reactions_available = {player_one: reaction_spend.unspent(), player_two: reaction_spend.unspent()}
    return state


async def _stamina(pool, player_id: str) -> int:
    row = await db_queries.get_player(player_id, conn=pool)
    assert row is not None
    return row["stamina"]["current"]


def _word_overlap(actual: str, expected: str) -> float:
    expected_words = set(normalized(expected).split())
    assert expected_words
    return len(set(normalized(actual).split()) & expected_words) / len(expected_words)


async def test_two_real_voices_spend_separately_in_one_reaction_window(
    livekit_server: dict[str, str], reset_db_pool: str
) -> None:
    harness = MultiplayerVoiceHarness(livekit_server)
    one, two = harness.player_one_identity, harness.player_two_identity
    userdata = SessionData(player_id=one, location_id="accord_guild_hall")
    state = _combat(one, two)
    userdata.combat_state = state
    assert state.open_window is not None
    original_window = dict(state.open_window)
    model = ActivateModel()
    pool = await db.get_pool()
    dm_session: AgentSession | None = None
    multiplayer_input: MultiplayerInput | None = None
    lifecycle: PartyLifecycle | None = None

    schema = ToolContext([activate]).parse_function_tools("anthropic", strict=True)[0]["input_schema"]
    assert set(schema["properties"]) == {"id", "target_id", "target_ids"}

    await seed_player_with_pools(pool, player_id=one, class_="guardian", stamina_current=10)
    await seed_player_with_pools(pool, player_id=two, class_="guardian", stamina_current=10)
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{level}', '5'::jsonb) WHERE player_id = ANY($1)",
        [one, two],
    )

    async def prepare_listener(room: rtc.Room):
        nonlocal dm_session, lifecycle
        lifecycle = _setup_party_join(
            room,
            userdata,
            queries=db_queries,
            resonance_mod=db_mutations_resonance,
            concentration_mod=db_mutations_concentration,
        )
        dm_session = AgentSession(llm=model, max_tool_steps=5, userdata=userdata)
        dm_session.output.set_audio_enabled(False)
        with fake_job_context(room=room):
            await dm_session.start(
                room=room,
                agent=Agent(instructions="Always call activate once, then acknowledge.", tools=[activate]),
                room_options=gameplay_room_options(userdata),
            )
        return lifecycle.authorize

    async def wait_for_spend(player_id: str, expected_turns: int) -> None:
        assert harness.manager is not None
        try:
            async with asyncio.timeout(30):
                while True:
                    spend = state.reactions_available[player_id]
                    if reaction_spend.is_spent(spend) and model.completed_turns >= expected_turns:
                        return
                    await asyncio.sleep(0.02)
        except TimeoutError as exc:
            assert lifecycle is not None
            pools = {one: await _stamina(pool, one), two: await _stamina(pool, two)}
            raise TimeoutError(
                f"reaction stalled: player={player_id}, turns={model.completed_turns}, "
                f"generations={{'{one}': {lifecycle.current_generation(one)}, "
                f"'{two}': {lifecycle.current_generation(two)}}}, pools={pools}, "
                f"spends={state.reactions_available}, users={model.user_turns}, "
                f"active={sorted(harness.manager.active_identities)}"
            ) from exc

    try:
        await harness.start(prepare_listener)
        assert harness.manager is not None and dm_session is not None and lifecycle is not None
        multiplayer_input = MultiplayerInput(harness.manager, lifecycle, dm_session, userdata)
        multiplayer_input.start()

        await harness.play(two, PLAYER_TWO_SPEECH)
        await wait_for_spend(two, 1)
        assert await _stamina(pool, two) == 7
        assert await _stamina(pool, one) == 10
        assert not reaction_spend.is_spent(state.reactions_available[one])

        await harness.play(one, PLAYER_ONE_SPEECH)
        await wait_for_spend(one, 2)
        assert await _stamina(pool, one) == 7
        assert await _stamina(pool, two) == 7
        assert state.open_window == original_window
        spends = state.reactions_available
        assert {spends[one]["window_id"], spends[two]["window_id"]} == {original_window["id"]}
        assert {spends[one]["held_seq"], spends[two]["held_seq"]} == {3}
        assert _word_overlap(model.user_turns[0], PLAYER_TWO_SPEECH.transcript) >= 0.75
        assert _word_overlap(model.user_turns[1], PLAYER_ONE_SPEECH.transcript) >= 0.75
        assert _word_overlap(model.user_turns[0], PLAYER_ONE_SPEECH.transcript) < 0.5
        assert _word_overlap(model.user_turns[1], PLAYER_TWO_SPEECH.transcript) < 0.5
    finally:
        if multiplayer_input is not None:
            await multiplayer_input.aclose()
        if dm_session is not None:
            await dm_session.aclose()
        if lifecycle is not None:
            await lifecycle.aclose()
        await harness.aclose()
        await pool.execute("DELETE FROM players WHERE player_id = ANY($1)", [one, two])
