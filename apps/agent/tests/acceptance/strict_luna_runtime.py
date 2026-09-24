"""Real LiveKit session runner, trace grader, and usage report for Luna cases."""

from __future__ import annotations

import json
import re
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from unittest.mock import patch

from acceptance.strict_luna_assertions import assert_case
from acceptance.strict_luna_scenarios import prepare_case
from livekit.agents.voice import AgentSession
from livekit.agents.voice.run_result import ChatMessageEvent, FunctionCallEvent
from sample_fixtures import FixedRng

from base_agent import BaseGameAgent
from blacksmith_agent import BLACKSMITH_TOOLS
from combat_agent import COMBAT_AGENT_TOOLS, CombatAgent
from creation_agent import CREATION_TOOLS
from creation_prompts import CREATION_SYSTEM_PROMPT
from dispatch_agent import DISPATCH_TOOLS
from exploration_agent import EXPLORATION_TOOLS, ExplorationAgent
from gameplay_llm import LUNA_MODEL, create_gameplay_llm, is_luna
from mode_prompts import BLACKSMITH_SYSTEM_PROMPT, DISPATCH_SYSTEM_PROMPT
from onboarding_agent import ONBOARDING_TOOLS, OnboardingAgent
from onboarding_prompt import build_onboarding_instructions
from system_prompts import COMBAT_SYSTEM_PROMPT, build_system_prompt
from voices import EMOTION_RATES, VOICE_ENV_VARS

REPORT_PATH = Path("/tmp/divineruin_strict_luna_gameplay.jsonl")
PRICE_SOURCE = "https://developers.openai.com/api/docs/models/gpt-6-luna"
PRICE_RETRIEVED = "2026-09-22"
INPUT_PER_MILLION = 0.10
CACHED_INPUT_PER_MILLION = 0.01
OUTPUT_PER_MILLION = 0.50


def _profile(case, sd) -> tuple[str, list]:
    profiles = {
        "exploration": (build_system_prompt(sd.location_id), EXPLORATION_TOOLS),
        "combat": (COMBAT_SYSTEM_PROMPT, COMBAT_AGENT_TOOLS),
        "dispatch": (DISPATCH_SYSTEM_PROMPT, DISPATCH_TOOLS),
        "onboarding": (build_onboarding_instructions(sd.onboarding_beat or 1, None), ONBOARDING_TOOLS),
        "blacksmith": (BLACKSMITH_SYSTEM_PROMPT, BLACKSMITH_TOOLS),
        "creation": (CREATION_SYSTEM_PROMPT, CREATION_TOOLS),
    }
    return profiles[case.profile]


def _message_text(event: ChatMessageEvent) -> str:
    return " ".join(part for part in event.item.content if isinstance(part, str)).strip()


def _narration(events: list[Any]) -> str:
    return " ".join(
        text
        for event in events
        if isinstance(event, ChatMessageEvent) and event.item.role == "assistant"
        if (text := _message_text(event))
    )


def _variant(call: Any, variant: str | None) -> bool:
    if variant is None:
        return True
    args = json.loads(call.arguments)
    if call.name == "query_info":
        return args.get("kind") == variant
    if call.name == "check":
        return args.get("roll", {}).get("kind") == variant
    if call.name == "travel":
        return args.get("mode") == variant
    if call.name == "enter_mode":
        return args.get("mode") == variant
    if call.name == "declare_phase":
        return any(row.get("kind") == variant for row in args.get("declarations", []))
    if call.name == "end_combat":
        return args.get("outcome") == variant
    if call.name == "resolve_activity":
        return args.get("kind") == variant
    if call.name == "begin_activity":
        activity = args.get("activity", {})
        if variant == "training_physical":
            return activity.get("kind") == "training" and activity.get("spell_id") is None
        if variant == "training_spell":
            return activity.get("kind") == "training" and bool(activity.get("spell_id"))
    if call.name == "activate":
        if variant == "self":
            return args.get("target_id") is None and args.get("target_ids") is None
        if variant in {"single", "reaction"}:
            return (args.get("target_id") is not None) is (variant == "single") and args.get("target_ids") is None
        if variant == "multiple":
            return len(args.get("target_ids") or []) == 2 and args.get("target_id") is None
    # No check covers this tool/variant pair, so the row's variant column would grade nothing.
    raise AssertionError(f"{call.name} has no variant check for {variant!r}")


def grade_trace(case, events: list[Any]) -> tuple[Any | None, str]:
    calls = [event.item for event in events if isinstance(event, FunctionCallEvent)]
    if case.expected_tool == "none":
        assert not calls, f"conversation made unexpected calls: {[call.name for call in calls]}"
        expected = None
    else:
        allowed = [case.expected_tool]
        if case.prerequisite:
            allowed.insert(0, case.prerequisite.split(":", 1)[0])
        names = [call.name for call in calls]
        if case.id == "creation.finalize_character":
            assert names[:1] == allowed and names[1:] == ["enter_location", "advance_onboarding_beat"], (
                f"expected finalize handoff calls, got {names}"
            )
            expected = calls[0]
        else:
            accepted = [allowed]
            if case.prerequisite:
                accepted.append([case.expected_tool])
            assert names in accepted, f"expected one of {accepted}, got {names}"
            expected = calls[-1]
        assert _variant(expected, case.expected_variant), (
            f"{case.id} expected variant {case.expected_variant!r}, got {expected.arguments}"
        )

    narration = _narration(events)
    assert narration, "Luna returned no final narration"
    assert case.narration_anchor.lower() in narration.lower(), (
        f"narration omitted anchor {case.narration_anchor!r}: {narration!r}"
    )
    if case.id in {"exploration.conversation", "exploration.query_inventory", "dispatch.query_training_programs"}:
        sentences = [part for part in re.split(r"(?<=[.!?])\s+", narration) if part.strip()]
        assert 1 <= len(sentences) <= 4, f"voice response has {len(sentences)} sentences: {narration!r}"
        for voice, emotion in re.findall(r"\[([A-Z0-9_]+),\s*([a-z_]+)\]:", narration):
            assert voice in VOICE_ENV_VARS, f"narration used unknown voice {voice!r}"
            assert emotion in EMOTION_RATES, f"narration used unknown emotion {emotion!r}"
    return expected, narration


def _cost(usage: dict[str, int]) -> float:
    uncached = usage["total_input"] - usage["total_cache_read"]
    return (
        uncached * INPUT_PER_MILLION
        + usage["total_cache_read"] * CACHED_INPUT_PER_MILLION
        + usage["total_output"] * OUTPUT_PER_MILLION
    ) / 1_000_000


def append_report(row: dict[str, Any]) -> None:
    with REPORT_PATH.open("a") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")


async def run_luna_case(case) -> dict[str, Any]:
    selected = create_gameplay_llm("unused-anthropic-model")
    assert is_luna(selected) is True
    assert selected.model == LUNA_MODEL
    scenario = await prepare_case(case.seed)
    if case.id == "exploration.enter_combat":
        import combat_agent

        # The shared fast-test fixture replaces this factory with MagicMock; this paid row
        # specifically measures LiveKit's real handoff binder.
        combat_agent.create_combat_agent = lambda chat_ctx=None: CombatAgent(chat_ctx=chat_ctx)
    instructions, tools = _profile(case, scenario.session_data)
    session = AgentSession(llm=selected, max_tool_steps=5, userdata=scenario.session_data)
    report: dict[str, Any] = {
        "id": case.id,
        "model": selected.model,
        "completion": "failed",
        "passed": False,
        "diagnostic": "runner did not complete",
        "calls": [],
        "request_count": 0,
        "input_tokens": 0,
        "cached_tokens": 0,
        "output_tokens": 0,
        "estimated_usd": 0.0,
        "price_source": PRICE_SOURCE,
        "price_retrieved": PRICE_RETRIEVED,
    }
    try:
        agent = (
            ExplorationAgent(initial_location=scenario.session_data.location_id)
            if case.id == "exploration.enter_combat"
            else BaseGameAgent(instructions=instructions, tools=tools)
        )
        roll_context = nullcontext()
        if case.id in {
            "exploration.check_gather",
            "exploration.check_social",
            "exploration.check_discover",
            "exploration.travel",
        }:
            import check_resolution

            resolve = check_resolution.resolve_skill_check_dc
            roll_context = patch(
                "check_resolution.resolve_skill_check_dc",
                side_effect=lambda player, skill, dc, rng=None: resolve(player, skill, dc, FixedRng(20)),
            )
        with (
            roll_context,
            scenario.session_data._bind_authenticated_actor(scenario.session_data.player_id, 1, lambda *_args: None),
        ):
            await session.start(agent)
            result = await session.run(user_input=case.prompt)
            report["calls"] = [event.item.name for event in result.events if isinstance(event, FunctionCallEvent)]
            expected_call, _ = grade_trace(case, result.events)
            await assert_case(case.assertion, scenario, result.events, expected_call)
        handoffs = {
            "exploration.enter_combat": CombatAgent,
            "combat.end_combat": ExplorationAgent,
            "dispatch.conclude": ExplorationAgent,
            "creation.finalize_character": OnboardingAgent,
        }
        if expected_agent := handoffs.get(case.id):
            assert isinstance(session.current_agent, expected_agent), (
                f"{case.id} did not hand off to {expected_agent.__name__}: {type(session.current_agent).__name__}"
            )
        report["completion"] = "completed"
        report["passed"] = True
        report["diagnostic"] = ""
    except Exception as exc:
        report["diagnostic"] = f"{type(exc).__name__}: {exc}"
    finally:
        usage = scenario.session_data.tokens.summary()
        report.update(
            request_count=usage["requests"],
            input_tokens=usage["total_input"],
            cached_tokens=usage["total_cache_read"],
            output_tokens=usage["total_output"],
            estimated_usd=_cost(usage),
        )
        if usage["requests"] == 0 or usage["total_input"] == 0 or usage["total_output"] == 0:
            report["passed"] = False
            report["completion"] = "failed"
            report["diagnostic"] = report["diagnostic"] or "provider usage was empty"
        append_report(report)
        await session.aclose()
        await selected.aclose()
    return report
