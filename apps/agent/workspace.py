"""Crafting workspace substrate (M5.2). Zero IO, zero async, deterministic.

Pure functions for the workspace layer: the WorkspaceType vocabulary + ordering
used by the three-check pipeline's Check 3 (story-003), settlement-by-size
availability, and rental pricing with disposition modifiers. DB reads (a player's
active rentals, an NPC's disposition) happen in the calling code; these take plain
args so they stay exhaustively unit-testable. Consumed by the three-check pipeline
(Check 3), crafting_tools.query_available_workspaces (pricing), and resolve_crafting.
"""

from enum import StrEnum


class WorkspaceType(StrEnum):
    """The four crafting workspaces. Values mirror Recipe.workspace_required
    (recipes.py) so a recipe's stored string maps straight onto a member."""

    FIELD = "field"
    WORKSHOP = "workshop"
    FORGE = "forge"
    LABORATORY = "laboratory"


# Field is the universal floor (Basic recipes, available everywhere); Workshop is
# the entry rental tier; Forge and Laboratory are the advanced (Expert-tier)
# workspaces. Forge and Laboratory share a rank because they are PARALLEL
# specializations — a forge cannot brew potions, a lab cannot smith metal — so
# neither subsumes the other. The rank separates basic (field/workshop) from
# advanced (forge/lab); the canonical Check-3 gate (story-003) is exact-type
# access, NOT rank >= (which would wrongly let a lab satisfy a forge recipe).
_WORKSPACE_RANK = {
    WorkspaceType.FIELD: 0,
    WorkspaceType.WORKSHOP: 1,
    WorkspaceType.FORGE: 2,
    WorkspaceType.LABORATORY: 2,
}


def workspace_rank(workspace_type: WorkspaceType) -> int:
    """Basic-vs-advanced ordering rank for `workspace_type` (field < workshop <
    forge == laboratory). See _WORKSPACE_RANK for why forge and lab tie.

    Callers holding a raw DB string (e.g. recipe.workspace_required) convert via
    WorkspaceType(value) first — that conversion fail-louds (ValueError) on an
    unknown workspace, so this stays a total lookup over the four members."""
    return _WORKSPACE_RANK[workspace_type]
