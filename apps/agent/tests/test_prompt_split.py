import ast
import json
from pathlib import Path
from unittest.mock import patch

from companion_profiles_config_fixture import load_fixture_config, setup_companion_profiles_config_fixture

AGENT_DIR = Path(__file__).resolve().parents[1]
BASELINE = Path(__file__).parent / "fixtures/prompt_split_baseline.json"
MOVED_COMPANION = {
    "_non_verbal_note",
    "build_companion_prompt",
    "build_companion_cue",
    "companion_voice_directive",
    "is_companion_cue",
}
MOVED_MODE = {
    "DISPATCH_MODE_PROMPT",
    "DISPATCH_SYSTEM_PROMPT",
    "BLACKSMITH_PROMPT",
    "BLACKSMITH_SYSTEM_PROMPT",
}


def render_prompts():
    from base_agent import BaseGameAgent
    from blacksmith_agent import BlacksmithAgent
    from combat_agent import CombatAgent
    from companion_prompts import (
        _non_verbal_note,
        build_companion_cue,
        build_companion_prompt,
        companion_voice_directive,
        is_companion_cue,
    )
    from creation_agent import CreationAgent
    from dispatch_agent import DispatchAgent
    from exploration_agent import ExplorationAgent
    from mode_prompts import (
        BLACKSMITH_PROMPT,
        BLACKSMITH_SYSTEM_PROMPT,
        DISPATCH_MODE_PROMPT,
        DISPATCH_SYSTEM_PROMPT,
    )
    from onboarding_agent import OnboardingAgent
    from session_data import CompanionState
    from system_prompts import build_system_prompt

    setup_companion_profiles_config_fixture()
    profiles = load_fixture_config()
    result = {
        "mode/BLACKSMITH_PROMPT": BLACKSMITH_PROMPT,
        "mode/BLACKSMITH_SYSTEM_PROMPT": BLACKSMITH_SYSTEM_PROMPT,
        "mode/DISPATCH_MODE_PROMPT": DISPATCH_MODE_PROMPT,
        "mode/DISPATCH_SYSTEM_PROMPT": DISPATCH_SYSTEM_PROMPT,
    }
    for companion_id, profile in sorted(profiles.items()):
        companion = CompanionState(companion_id, profile.name)
        result[f"companion/{companion_id}/non_verbal_note"] = _non_verbal_note(profile.name)
        for level in (1, 20):
            result[f"companion/{companion_id}/prompt/{level}"] = build_companion_prompt(companion_id, level)
        cue = build_companion_cue(companion, "waits by the gate.", "curious")
        result[f"companion/{companion_id}/cue"] = cue
        result[f"companion/{companion_id}/voice"] = companion_voice_directive(companion)
        result[f"companion/{companion_id}/is_cue/match"] = str(is_companion_cue(cue, companion))
        result[f"companion/{companion_id}/is_cue/miss"] = str(is_companion_cue("No companion speaks here.", companion))

    regions = (
        ("city", "accord_guild_hall"),
        ("wilderness", "greyvale_crossroads"),
        ("dungeon", "hollow_crypt_entrance"),
    )
    for region, location in regions:
        for presence in ("absent", "present", "away"):
            companion = (
                None if presence == "absent" else CompanionState("companion_kael", "Kael", 20, presence == "present")
            )
            result[f"system/{region}/{presence}"] = build_system_prompt(location, companion)

    captured = []

    def capture(self, instructions, **kwargs):
        captured.append(instructions)

    with patch.object(BaseGameAgent, "__init__", capture):
        for region, location in regions:
            captured.clear()
            ExplorationAgent(
                initial_location=location,
                companion=CompanionState("companion_kael", "Kael", 20),
                region_type=region,
            )
            result[f"agent/exploration/{region}"] = captured.pop()
        for name, cls in (
            ("combat", CombatAgent),
            ("dispatch", DispatchAgent),
            ("blacksmith", BlacksmithAgent),
            ("creation", CreationAgent),
        ):
            captured.clear()
            cls()
            result[f"agent/{name}"] = captured.pop()
        captured.clear()
        OnboardingAgent(onboarding_beat=3, companion_id="companion_kael")
        result["agent/onboarding"] = captured.pop()
    return result


def test_prompts_match_pre_split_baseline():
    expected = json.loads(BASELINE.read_text())
    actual = render_prompts()
    assert len(expected) == 49
    assert expected.keys() == actual.keys()
    assert all(isinstance(value, str) and value for value in actual.values())
    assert actual == expected


def test_moved_names_have_one_home_and_importers_are_current():
    modules = [path for path in AGENT_DIR.rglob("*.py") if ".venv" not in path.parts]
    assert modules
    imports = {"system_prompts": 0, "companion_prompts": 0, "mode_prompts": 0}
    for path in modules:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in imports:
                imports[node.module] += 1
                if node.module == "system_prompts":
                    assert not ({alias.name for alias in node.names} & (MOVED_COMPANION | MOVED_MODE)), path
    assert all(imports.values()), imports
    for module_name, moved in (
        ("system_prompts", MOVED_COMPANION | MOVED_MODE),
        ("companion_prompts", MOVED_COMPANION),
        ("mode_prompts", MOVED_MODE),
    ):
        tree = ast.parse((AGENT_DIR / f"{module_name}.py").read_text())
        defined = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                defined.update(target.id for target in node.targets if isinstance(target, ast.Name))
        if module_name == "system_prompts":
            assert not (defined & moved)
        else:
            assert moved <= defined


def test_prompt_modules_leave_room_under_cap():
    for name in ("system_prompts", "companion_prompts", "mode_prompts"):
        assert len((AGENT_DIR / f"{name}.py").read_text().splitlines()) <= 400, name
