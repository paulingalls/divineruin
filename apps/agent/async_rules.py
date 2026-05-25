"""Pure-function async activity resolution. Zero IO, zero async.

All resolution functions accept an optional `rng` for deterministic testing.
Slot/dispatch validation lives in the TS server (apps/server/src/slot_validation.ts,
errand_risk.ts). Errand risk is rolled at resolution by the async worker via
errand_risk.py (ADR 0006); these functions compute the skill-check outcome only.
"""

import random
from dataclasses import dataclass

from crafting_gates import tainted_blocks_crafter, workspace_accessible
from rules_engine import attribute_modifier, dc_for_tier, skill_modifier

# --- Outcome dataclasses ---


@dataclass(frozen=True)
class CraftingOutcome:
    tier: str  # success | partial | unexpected | failure
    crafted_item_id: str | None
    crafted_item_name: str | None
    quality_bonus: int
    materials_consumed: list[str]
    materials_returned: list[str]
    narrative_context: dict
    decision_options: list[dict]


@dataclass(frozen=True)
class ErrandOutcome:
    tier: str  # great_success | success | partial | complication
    errand_type: str
    information_gained: list[str]
    items_acquired: list[dict]
    relationship_change: int
    narrative_context: dict
    decision_options: list[dict]


# --- Resolution functions ---


def resolve_crafting(
    player_data: dict,
    parameters: dict,
    *,
    workspace_access: list[str] | None = None,
    crafting_tier: str | None = None,
    rng: random.Random | None = None,
) -> CraftingOutcome:
    """Resolve a crafting activity: re-check the workspace-access and tainted-Expert
    gates, then roll d20+mod vs DC.

    The gates were already run at creation for the agent tool path, but the live REST
    create path skips pre-flight (concern 2b76f2452f23), so resolution is the chokepoint
    that catches an insufficient workspace or a sub-Expert working tainted materials. A
    gate FAILURE is a `failure` outcome (materials consumed, no item) — not an exception.

    `workspace_access` (the player's accessible workspaces, captured at creation) and
    `crafting_tier` are REQUIRED: the worker threads them from the activity parameters,
    and they fail loud (ValueError) if absent rather than silently defaulting, so a
    miswired producer surfaces immediately instead of mis-gating the craft.
    """
    if workspace_access is None:
        raise ValueError("resolve_crafting requires workspace_access captured at creation")
    if crafting_tier is None:
        raise ValueError("resolve_crafting requires crafting_tier captured at creation")

    r = rng or random.Random()

    required_materials = parameters.get("required_materials", [])
    recipe_id = parameters.get("recipe_id", "unknown")
    result_item_id = parameters.get("result_item_id", recipe_id)
    result_item_name = parameters.get("result_item_name", "crafted item")

    workspace_required = parameters.get("workspace_required")
    if workspace_required is None:
        raise ValueError("resolve_crafting requires parameters['workspace_required'] captured at creation")
    if "tainted_materials" not in parameters:
        raise ValueError("resolve_crafting requires parameters['tainted_materials'] captured at creation")
    tainted_materials = parameters["tainted_materials"]

    # Resolution-time gates (story-005). Evaluated BEFORE the roll so a gate failure
    # consumes no rng (deterministic regardless of seed). Materials were deducted at
    # creation, so a gate failure consumes them and returns no item — the spec's
    # failure tier. The gates reuse the same predicates as the pre-flight pipeline.
    gate = None
    gate_reason = ""
    if not workspace_accessible(workspace_required, workspace_access):
        gate, gate_reason = "workspace", f"no access to a {workspace_required} workspace"
    elif tainted_blocks_crafter(crafting_tier, tainted_materials):
        gate, gate_reason = "tainted_expert", f"{crafting_tier} crafting cannot safely work tainted materials"
    if gate is not None:
        return CraftingOutcome(
            tier="failure",
            crafted_item_id=None,
            crafted_item_name=None,
            quality_bonus=0,
            materials_consumed=list(required_materials),
            materials_returned=[],
            narrative_context={
                "tier": "failure",
                "gate": gate,
                "gate_reason": gate_reason,
                "recipe_name": result_item_name,
            },
            decision_options=[
                {"id": "retry", "label": "Set the work aside for now"},
                {"id": "abandon", "label": "Walk away from the bench"},
            ],
        )

    # Skill check for crafting
    craft_skill = parameters.get("skill", "arcana")
    dc = parameters.get("dc", dc_for_tier("moderate"))
    mod = skill_modifier(player_data, craft_skill)
    d20 = r.randint(1, 20)
    total = d20 + mod
    margin = total - dc

    if d20 == 20 or margin >= 5:
        tier = "success"
        quality_bonus = min(margin, 3)
        materials_consumed = list(required_materials)
        materials_returned = []
        crafted_item_id = result_item_id
        crafted_item_name = result_item_name
        decisions = [
            {"id": "keep", "label": "Keep the item"},
            {"id": "sell", "label": "Set it aside to sell"},
        ]
    elif margin >= 0:
        tier = "partial"
        quality_bonus = 0
        materials_consumed = list(required_materials)
        materials_returned = []
        crafted_item_id = result_item_id
        crafted_item_name = result_item_name
        decisions = [
            {"id": "keep", "label": "Keep it as-is"},
            {"id": "rework", "label": "Try to improve it (risk breaking)"},
        ]
    elif d20 == 1 or margin < -5:
        tier = "failure"
        quality_bonus = 0
        # Return half materials on failure
        half = len(required_materials) // 2
        materials_consumed = required_materials[:half]
        materials_returned = required_materials[half:]
        crafted_item_id = None
        crafted_item_name = None
        decisions = [
            {"id": "retry", "label": "Salvage what you can and try again later"},
            {"id": "abandon", "label": "Walk away from the forge"},
        ]
    else:
        tier = "unexpected"
        quality_bonus = 0
        materials_consumed = list(required_materials)
        materials_returned = []
        crafted_item_id = result_item_id
        crafted_item_name = result_item_name
        decisions = [
            {"id": "keep_odd", "label": "Keep it — it might be useful"},
            {"id": "show_scholar", "label": "Show it to a scholar"},
        ]

    narrative_context = {
        "tier": tier,
        "roll": d20,
        "total": total,
        "dc": dc,
        "skill": craft_skill,
        "recipe_name": result_item_name,
        "quality_bonus": quality_bonus,
        "npc_id": parameters.get("npc_id", "grimjaw_blacksmith"),
    }

    return CraftingOutcome(
        tier=tier,
        crafted_item_id=crafted_item_id,
        crafted_item_name=crafted_item_name,
        quality_bonus=quality_bonus,
        materials_consumed=materials_consumed,
        materials_returned=materials_returned,
        narrative_context=narrative_context,
        decision_options=decisions,
    )


def resolve_companion_errand(
    companion_data: dict,
    parameters: dict,
    rng: random.Random | None = None,
) -> ErrandOutcome:
    """Resolve a companion errand based on errand type and companion abilities."""
    r = rng or random.Random()

    errand_type = parameters.get("errand_type", "scout")
    destination = parameters.get("destination", "unknown")
    relationship_tier = companion_data.get("relationship_tier", 1)

    # Companion skill check — higher relationship = better results
    base_roll = r.randint(1, 20)
    relationship_bonus = min(relationship_tier, 4)
    total = base_roll + relationship_bonus

    # Errand-type specific skill bonus
    companion_attrs = companion_data.get("attributes", {})
    if errand_type == "scout":
        total += attribute_modifier(companion_attrs.get("wisdom", 12))
    elif errand_type == "social":
        total += attribute_modifier(companion_attrs.get("charisma", 11))
    elif errand_type == "acquire":
        total += attribute_modifier(companion_attrs.get("intelligence", 10))
    elif errand_type == "relationship":
        total += attribute_modifier(companion_attrs.get("charisma", 11))

    dc = parameters.get("dc", 12)
    margin = total - dc

    items_acquired: list[dict] = []
    relationship_change = 0

    if margin >= 8:
        tier = "great_success"
        info = parameters.get("great_success_info", [f"Discovered something significant at {destination}"])
        items_acquired = parameters.get("great_success_items", [])
        relationship_change = 1
        decisions = [
            {"id": "praise", "label": "Tell them they did well"},
            {"id": "investigate", "label": "Ask them to tell you more"},
        ]
    elif margin >= 0:
        tier = "success"
        info = parameters.get("success_info", [f"Found what they were looking for at {destination}"])
        items_acquired = parameters.get("success_items", [])
        relationship_change = 0
        decisions = [
            {"id": "thank", "label": "Thank them for the help"},
            {"id": "follow_up", "label": "Send them back for more"},
        ]
    elif margin >= -5:
        tier = "partial"
        info = parameters.get("partial_info", [f"Returned from {destination} with incomplete findings"])
        relationship_change = 0
        decisions = [
            {"id": "reassure", "label": "Reassure them it's enough"},
            {"id": "push", "label": "Ask them to try harder next time"},
        ]
    else:
        tier = "complication"
        info = parameters.get("complication_info", [f"Something went wrong at {destination}"])
        relationship_change = -1
        decisions = [
            {"id": "comfort", "label": "Make sure they're alright"},
            {"id": "dismiss", "label": "It doesn't matter, move on"},
        ]

    narrative_context = {
        "tier": tier,
        "roll": base_roll,
        "total": total,
        "dc": dc,
        "errand_type": errand_type,
        "destination": destination,
        "companion_name": companion_data.get("name", "Kael"),
        "companion_id": companion_data.get("id", "companion_kael"),
    }

    return ErrandOutcome(
        tier=tier,
        errand_type=errand_type,
        information_gained=info,
        items_acquired=items_acquired,
        relationship_change=relationship_change,
        narrative_context=narrative_context,
        decision_options=decisions,
    )
