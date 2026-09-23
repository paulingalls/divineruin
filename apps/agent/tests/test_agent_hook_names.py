import pytest
from livekit.agents import Agent

import base_agent
import blacksmith_agent
import combat_agent
import creation_agent
import dispatch_agent
import exploration_agent
import multiplayer_transcription
import onboarding_agent
import prologue_agent

PROJECT_MODULES = {
    module.__name__
    for module in (
        base_agent,
        blacksmith_agent,
        combat_agent,
        creation_agent,
        dispatch_agent,
        exploration_agent,
        multiplayer_transcription,
        onboarding_agent,
        prologue_agent,
    )
}


def _descendants(base):
    for subclass in base.__subclasses__():
        yield subclass
        yield from _descendants(subclass)


def _check_hooks(classes):
    for cls in classes:
        for name in cls.__dict__:
            if name.startswith("on_") and not hasattr(Agent, name):
                raise AssertionError(f"{cls.__name__}.{name} is not a LiveKit Agent hook")


def test_project_agent_hooks_exist_on_installed_livekit_agent():
    classes = [cls for cls in _descendants(Agent) if cls.__module__ in PROJECT_MODULES]
    assert {cls.__name__ for cls in classes} >= {
        "BaseGameAgent",
        "BlacksmithAgent",
        "ExplorationAgent",
        "CombatAgent",
        "CreationAgent",
        "OnboardingAgent",
        "PrologueAgent",
        "DispatchAgent",
        "_TranscriberAgent",
    }
    _check_hooks(classes)


def test_misspelled_hook_is_rejected(monkeypatch):
    monkeypatch.setattr(exploration_agent.ExplorationAgent, "on_agent_turn_completed", lambda self: None, raising=False)
    with pytest.raises(AssertionError, match="on_agent_turn_completed"):
        _check_hooks([exploration_agent.ExplorationAgent])
