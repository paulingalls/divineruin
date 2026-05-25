"""Shared crafting gate predicates. Pure, zero IO.

The workspace exact-type access check and the tainted-Expert check each have ONE
definition here, consumed by both the pre-flight pipeline (preflight_pipeline.py,
at creation) and async resolution (async_rules.resolve_crafting). Keeping a single
definition stops the two call sites from drifting (chokepoint).
"""

from collections.abc import Iterable

from rules_engine import SKILL_TIER_ORDER
from workspace import WorkspaceType


def workspace_accessible(workspace_required: str, accessible_workspaces: Iterable[str]) -> bool:
    """True if the recipe's required workspace is among the accessible ones.

    Exact-type access — a laboratory does NOT satisfy a forge recipe even though
    they share an advanced rank (workspace-check3-access). `workspace_required`
    converts via WorkspaceType first, so an unknown workspace fails loud
    (ValueError) rather than silently failing the gate; the accessible strings are
    compared as-is (WorkspaceType is a StrEnum, so member == value).
    """
    required = WorkspaceType(workspace_required)
    return required in set(accessible_workspaces)


def tainted_blocks_crafter(crafting_tier: str, tainted_materials: bool) -> bool:
    """True if the craft must be refused: working tainted (Hollow-touched)
    materials requires at least Expert crafting (spec §Resolution Flow Check 5).

    Untainted never blocks (and the tier is not examined — mirrors Check 5's
    short-circuit). When tainted, an unknown crafting tier fails loud.
    """
    if not tainted_materials:
        return False
    if crafting_tier not in SKILL_TIER_ORDER:
        raise ValueError(f"crafting_tier {crafting_tier!r} is not a valid crafting tier")
    return SKILL_TIER_ORDER.index(crafting_tier) < SKILL_TIER_ORDER.index("expert")
