"""The LLM-facing edge of the three sum-typed verbs: raw tool-call JSON in, engine args out.

Every other test of the ADR 0008 reshape starts from a variant the test constructed. Production
never does: the model emits JSON, LiveKit validates it against the tool signature and hands the
tool typed variants (`prepare_function_arguments` — the same call the agent runtime makes before
invoking a tool). That step is where the discriminated union either resolves or does not, and it
is untested by the mapper suites.

Only `begin_activity` has live evidence for it — `tests/acceptance/features/` holds two features
and both drive DispatchAgent. Nothing drives ExplorationAgent or CombatAgent with a real LLM, and
the schema walk in test_strict_tool_budget pins the emitted SCHEMA, not the round trip. So `check`
and `declare_phase` would otherwise ship their whole LLM path unexercised: reshape the parameter —
wrap the union a level deeper, take a bare dict again, rename a field the mapper reads — and every
combat and exploration turn breaks with the mapper suites still green.

NOT the `Annotated[..., Field(discriminator="kind")]` wrapper specifically: dropping it was
measured (2026-09-05) to leave both this file and production behaviour unchanged, because every
variant tags `kind` with a `const` and pydantic's smart union resolves on it. The discriminator
buys a sharper validation error, not correctness, so nothing here reds on its removal.
"""

import inspect
import json
from unittest.mock import MagicMock

import pytest
from livekit.agents.llm import ToolError
from livekit.agents.llm.utils import prepare_function_arguments
from livekit.agents.voice import RunContext

import activity_payloads
import check_payloads
import declaration_payloads
from activity_tools import begin_activity
from check_tools import check
from combat_turn import declare_phase
from session_data import SessionData


def _call_ctx() -> RunContext:
    """A context `prepare_function_arguments` will actually inject.

    It type-checks the parameter with `isinstance(call_ctx, RunContext)` and SILENTLY drops a
    context that fails — which then surfaces as "missing a required argument: 'context'", not as
    anything about the payload. spec= is what makes the mock pass that check.
    """
    ctx = MagicMock(spec=RunContext)
    ctx.userdata = SessionData(player_id="player_1", location_id="accord_guild_hall")
    return ctx


def _bind(tool, arguments: dict) -> dict:
    """Run one raw tool call through LiveKit's validation and name what the tool would receive."""
    args, kwargs = prepare_function_arguments(fnc=tool, json_arguments=json.dumps(arguments), call_ctx=_call_ctx())
    return dict(inspect.signature(tool).bind(*args, **kwargs).arguments)


def test_declare_phase_binds_raw_json_declarations_to_the_engine_dict():
    bound = _bind(
        declare_phase,
        {
            "declarations": [
                {
                    "kind": "attack",
                    "actor_id": "player_1",
                    "action": "Longsword",
                    "target_id": "goblin_1",
                    "rider": "",
                },
                {"kind": "defend", "actor_id": "goblin_1"},
            ]
        },
    )
    engine = declaration_payloads.to_engine_declarations(bound["declarations"])
    assert engine == {
        "player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_1"},
        "goblin_1": {"type": "defend"},
    }


def test_check_binds_a_raw_json_roll_to_the_impl_args():
    bound = _bind(check, {"roll": {"kind": "gather", "category": "any"}})
    assert check_payloads.to_impl_args(bound["roll"]) == ("gather", {"target": ""})


def test_begin_activity_binds_a_raw_json_activity_to_the_impl_kwargs():
    bound = _bind(
        begin_activity,
        {
            "activity": {
                "kind": "experiment",
                "materials": [{"material_id": "iron_ore", "quantity": 2}],
                "intended_output": "iron_ingot",
            }
        },
    )
    assert activity_payloads.to_impl_kwargs(bound["activity"]) == (
        "experiment",
        {"material_ids": ["iron_ore"], "quantities": [2], "intended_output": "iron_ingot"},
    )


@pytest.mark.parametrize(
    "tool,arguments",
    [
        (declare_phase, {"declarations": [{"kind": "sing", "actor_id": "player_1"}]}),
        (check, {"roll": {"kind": "skill", "skill": "athletics"}}),
        (begin_activity, {"activity": {"kind": "training"}}),
    ],
)
def test_an_unknown_kind_or_a_missing_required_field_is_a_self_correctable_tool_error(tool, arguments):
    """ADR 0008 rule 2 made every variant field required, so a field the model omits is now a
    validation failure rather than a defaulted empty string. It must reach the model as a
    ToolError it can retry from — not as a raw ValidationError out of the tool call."""
    with pytest.raises(ToolError):
        _bind(tool, arguments)
