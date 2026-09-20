"""wait_for_output is the runner's 'the agent actually finished an audible turn' gate."""

from __future__ import annotations

import pytest

from voice_replay_audio import wait_for_output


class _Session:
    """Replays a scripted agent_state sequence, holding the last state once exhausted."""

    def __init__(self, states: list[str]):
        self._states = states

    @property
    def agent_state(self) -> str:
        return self._states.pop(0) if len(self._states) > 1 else self._states[0]


async def test_settled_listening_after_speech_completes_the_turn():
    await wait_for_output(
        _Session(["initializing", "speaking", "listening"]),
        affected=True,
        tool_events=["check"],
        timeout=5.0,
        stable_seconds=0.1,
    )


@pytest.mark.parametrize(
    ("states", "affected", "tool_events"),
    [
        (["listening"], False, []),  # never spoke: no audible output at all
        (["speaking"], False, []),  # still speaking when the budget ran out
        (["speaking", "listening"], True, []),  # spoke, but the affected turn ran no tool
    ],
)
async def test_incomplete_turns_time_out_loudly(states, affected: bool, tool_events):
    with pytest.raises(TimeoutError, match="no complete audible turn"):
        await wait_for_output(
            _Session(states), affected=affected, tool_events=tool_events, timeout=0.3, stable_seconds=0.1
        )
