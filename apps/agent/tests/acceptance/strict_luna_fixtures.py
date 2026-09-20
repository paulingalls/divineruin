"""Side-effect-free manifest contract for the seeded Luna gameplay matrix."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_CASE_IDS = frozenset(
    {
        "exploration.enter_location",
        "exploration.query_inventory",
        "exploration.check_gather",
        "exploration.check_skill",
        "exploration.check_social",
        "exploration.check_discover",
        "exploration.check_save",
        "exploration.check_dice",
        "exploration.travel",
        "exploration.activate_self",
        "exploration.activate_single",
        "exploration.activate_multiple",
        "exploration.enter_combat",
        "exploration.conversation",
        "combat.declare_multi_actor",
        "combat.resolve_phase",
        "combat.activate_reaction",
        "combat.end_combat",
        "dispatch.query_training_programs",
        "dispatch.begin_physical_training",
        "dispatch.begin_spell_training",
        "dispatch.resolve_midpoint",
        "dispatch.conclude",
        "onboarding.advance_beat",
        "blacksmith.repair_item",
        "creation.set_choice",
        "creation.finalize_character",
    }
)

PROFILES = frozenset(case_id.split(".", 1)[0] for case_id in REQUIRED_CASE_IDS)
TOOLS = frozenset(
    {
        "activate",
        "advance_onboarding_beat",
        "begin_activity",
        "check",
        "conclude_dispatch",
        "declare_phase",
        "end_combat",
        "enter_location",
        "enter_mode",
        "finalize_character",
        "none",
        "query_info",
        "repair_item",
        "resolve_activity",
        "resolve_phase",
        "set_creation_choice",
        "travel",
    }
)
VARIANTS = frozenset(
    {
        "abilities",
        "attack",
        "combat",
        "dice",
        "discover",
        "gather",
        "inventory",
        "multiple",
        "none",
        "reaction",
        "save",
        "scenic",
        "self",
        "single",
        "skill",
        "social",
        "training",
        "training_physical",
        "training_programs",
        "training_spell",
        "victory",
    }
)
PREREQUISITES = frozenset({None, "enter_location", "query_info:abilities", "query_info:training_programs"})
SEEDS = REQUIRED_CASE_IDS
ASSERTIONS = REQUIRED_CASE_IDS
MANIFEST_PATH = Path(__file__).with_name("strict_luna_case_manifest.json")


@dataclass(frozen=True)
class LunaCase:
    id: str
    profile: str
    seed: str
    prompt: str
    expected_tool: str
    expected_variant: str | None
    prerequisite: str | None
    assertion: str
    narration_anchor: str


def _nonempty_string(row: dict[str, Any], field: str, case_id: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{case_id}: {field} must be a non-empty string")
    return value


def _parse_row(raw: Any, index: int) -> LunaCase:
    if not isinstance(raw, dict):
        raise ValueError(f"row {index}: expected an object")
    expected_fields = set(LunaCase.__dataclass_fields__)
    unknown_fields = sorted(set(raw) - expected_fields)
    if unknown_fields:
        raise ValueError(f"row {index}: unknown fields {unknown_fields}")
    case_id = _nonempty_string(raw, "id", f"row {index}")
    profile = _nonempty_string(raw, "profile", case_id)
    seed = _nonempty_string(raw, "seed", case_id)
    prompt = _nonempty_string(raw, "prompt", case_id)
    tool = _nonempty_string(raw, "expected_tool", case_id)
    assertion = _nonempty_string(raw, "assertion", case_id)
    anchor = _nonempty_string(raw, "narration_anchor", case_id)
    variant = raw.get("expected_variant")
    prerequisite = raw.get("prerequisite")

    checks = (
        (profile in PROFILES, "profile", profile),
        (seed in SEEDS, "seed", seed),
        (tool in TOOLS, "tool", tool),
        (variant is None or variant in VARIANTS, "variant", variant),
        (prerequisite in PREREQUISITES, "prerequisite", prerequisite),
        (assertion in ASSERTIONS, "assertion", assertion),
    )
    for valid, label, value in checks:
        if not valid:
            raise ValueError(f"{case_id}: unknown {label} {value!r}")
    if profile != case_id.split(".", 1)[0]:
        raise ValueError(f"{case_id}: profile does not match id")

    return LunaCase(case_id, profile, seed, prompt, tool, variant, prerequisite, assertion, anchor)


def load_case_manifest(path: Path | None = None) -> tuple[LunaCase, ...]:
    manifest = MANIFEST_PATH if path is None else path
    if not manifest.is_file():
        raise FileNotFoundError(f"Luna gameplay manifest is missing: {manifest}")
    try:
        raw = json.loads(manifest.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed Luna gameplay manifest: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise ValueError("Luna gameplay manifest is empty")

    cases = tuple(_parse_row(row, index) for index, row in enumerate(raw))
    ids = [case.id for case in cases]
    duplicates = sorted(case_id for case_id in set(ids) if ids.count(case_id) > 1)
    if duplicates:
        raise ValueError(f"duplicate Luna gameplay ids: {duplicates}")
    unknown = sorted(set(ids) - REQUIRED_CASE_IDS)
    missing = sorted(REQUIRED_CASE_IDS - set(ids))
    if unknown:
        raise ValueError(f"unknown Luna gameplay ids: {unknown}")
    if missing:
        raise ValueError(f"missing Luna gameplay ids: {missing}")
    return cases


async def run_luna_case(case: LunaCase) -> dict[str, Any]:
    from acceptance.strict_luna_runtime import run_luna_case as run

    return await run(case)
