"""Crafting workspace substrate (M5.2). Zero IO, zero async, deterministic.

Pure functions for the workspace layer: the WorkspaceType vocabulary + ordering
used by the three-check pipeline's Check 3 (story-003), settlement-by-size
availability, and rental pricing with disposition modifiers. DB reads (a player's
active rentals, an NPC's disposition) happen in the calling code; these take plain
args so they stay exhaustively unit-testable. Consumed by the three-check pipeline
(Check 3), crafting_tools.query_available_workspaces (pricing), and resolve_crafting.
"""

from dataclasses import dataclass
from enum import IntEnum, StrEnum

from tool_support import DISPOSITION_TIERS


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


# Rental base price in silver pieces per calendar day (spec §Workspace Access).
# Field is omitted: it is free and always available, never rented.
RENTAL_BASE_PRICE_SP: dict[WorkspaceType, int] = {
    WorkspaceType.WORKSHOP: 2,
    WorkspaceType.FORGE: 5,
    WorkspaceType.LABORATORY: 10,
}

# A city (or Keldaran hold) may rent Forge + Laboratory together as a discounted
# bundle (12sp < 5+10). It is a rental OPTION, not a WorkspaceType member — no
# recipe ever *requires* "combined" — so it lives as its own price constant.
COMBINED_FORGE_LAB_RENTAL_SP = 12

# Disposition price multipliers (spec §Rental rules: Friendly 80%, Trusted 60%);
# Neutral-and-up not listed here pays full price. Below Neutral the NPC refuses
# outright — no rental, no surcharge (adopted over the milestone's hostile-
# surcharge wording). The below-Neutral test reuses tool_support.DISPOSITION_TIERS
# rather than re-listing the disposition scale here.
_RENTAL_MULTIPLIER = {"friendly": 0.8, "trusted": 0.6}


@dataclass(frozen=True)
class RentalQuote:
    available: bool
    price_sp: float  # 0.0 when not available
    reason: str  # "" when available


def compute_rental_price(base_price_sp: int, disposition: str) -> RentalQuote:
    """Apply an NPC's `disposition` to a workspace's `base_price_sp` (sp/day).

    `base_price_sp` comes from RENTAL_BASE_PRICE_SP[workspace_type] or
    COMBINED_FORGE_LAB_RENTAL_SP — taking the price (not the type) lets the
    Forge+Laboratory bundle reuse the same disposition logic. Returns an
    unavailable RentalQuote when the NPC's disposition is below Neutral (a forge
    is not rented to the unfriendly). Raises ValueError on an unknown disposition.
    """
    key = disposition.lower()
    rank = DISPOSITION_TIERS.get(key)
    if rank is None:
        raise ValueError(f"unknown disposition {disposition!r}")
    if rank < DISPOSITION_TIERS["neutral"]:
        return RentalQuote(False, 0.0, f"NPC refuses to rent at {key} disposition (below neutral)")
    return RentalQuote(True, base_price_sp * _RENTAL_MULTIPLIER.get(key, 1.0), "")


class Availability(IntEnum):
    """How likely a settlement of a given size is to offer a workspace (spec
    §Settlement Workspace Availability). Ordered so downstream gates can ask
    e.g. `>= SOMETIMES`; NEVER means the workspace is absent at that size."""

    NEVER = 0
    RARELY = 1
    SOMETIMES = 2
    USUALLY = 3
    ALWAYS = 4


class SettlementSize(StrEnum):
    HAMLET = "hamlet"
    VILLAGE = "village"
    TOWN = "town"
    CITY = "city"
    KELDARAN_HOLD = "keldaran_hold"


# Settlement workspace availability (spec §Settlement Workspace Availability).
# Field is omitted here — it is ALWAYS available everywhere (see the guard in
# settlement_workspace_availability), so only the three rentable workspaces vary
# by settlement size. This encodes the spec table 1:1.
_SETTLEMENT_AVAILABILITY: dict[SettlementSize, dict[WorkspaceType, Availability]] = {
    SettlementSize.HAMLET: {
        WorkspaceType.WORKSHOP: Availability.SOMETIMES,
        WorkspaceType.FORGE: Availability.NEVER,
        WorkspaceType.LABORATORY: Availability.NEVER,
    },
    SettlementSize.VILLAGE: {
        WorkspaceType.WORKSHOP: Availability.USUALLY,
        WorkspaceType.FORGE: Availability.RARELY,
        WorkspaceType.LABORATORY: Availability.NEVER,
    },
    SettlementSize.TOWN: {
        WorkspaceType.WORKSHOP: Availability.ALWAYS,
        WorkspaceType.FORGE: Availability.USUALLY,
        WorkspaceType.LABORATORY: Availability.RARELY,
    },
    SettlementSize.CITY: {
        WorkspaceType.WORKSHOP: Availability.ALWAYS,
        WorkspaceType.FORGE: Availability.ALWAYS,
        WorkspaceType.LABORATORY: Availability.USUALLY,
    },
    SettlementSize.KELDARAN_HOLD: {
        WorkspaceType.WORKSHOP: Availability.ALWAYS,
        WorkspaceType.FORGE: Availability.ALWAYS,
        WorkspaceType.LABORATORY: Availability.SOMETIMES,
    },
}


def settlement_workspace_availability(size: SettlementSize, workspace_type: WorkspaceType) -> Availability:
    """How likely a `size` settlement is to offer `workspace_type` (spec matrix).

    Field is always available everywhere (the universal floor); the other three
    workspaces follow the per-size table. This is a total lookup over the four
    members for each size, so no KeyError is possible for valid enum inputs."""
    if workspace_type is WorkspaceType.FIELD:
        return Availability.ALWAYS
    return _SETTLEMENT_AVAILABILITY[size][workspace_type]
