"""Pure-function async activity resolution. Zero IO, zero async.

All resolution functions accept an optional `rng` for deterministic testing.
"""

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from rules_engine import attribute_modifier, skill_modifier

# --- Constants ---

MAX_CONCURRENT_ACTIVITIES = 4

VALID_ACTIVITY_TYPES = {"crafting", "training", "companion_errand"}

VALID_ERRAND_TYPES = {"scout", "social", "acquire", "relationship"}

CRAFTING_OUTCOME_TIERS = ("success", "partial", "unexpected", "failure")
TRAINING_OUTCOME_TIERS = ("breakthrough", "plateau", "redirection")
ERRAND_OUTCOME_TIERS = ("great_success", "success", "partial", "complication")


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
class TrainingOutcome:
    tier: str  # breakthrough | plateau | redirection
    stat_gains: dict  # e.g. {"strength": 1} or {"skill_bonus": "athletics"}
    ability_unlocked: str | None
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


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)


# --- Core functions ---


def compute_resolve_time(
    min_seconds: int,
    max_seconds: int,
    start_time: datetime | None = None,
    rng: random.Random | None = None,
) -> datetime:
    """Compute a randomized resolve time within the soft range."""
    r = rng or random.Random()
    duration = r.randint(min_seconds, max_seconds)
    base = start_time or datetime.now(UTC)
    return base + timedelta(seconds=duration)


def validate_activity_params(
    activity_type: str,
    parameters: dict,
    player_data: dict,
    active_count: int,
) -> ValidationResult:
    """Validate activity creation parameters. Pure — no IO."""
    errors: list[str] = []

    if activity_type not in VALID_ACTIVITY_TYPES:
        errors.append(f"Invalid activity type: {activity_type}")
        return ValidationResult(valid=False, errors=errors)

    if active_count >= MAX_CONCURRENT_ACTIVITIES:
        errors.append(f"Maximum {MAX_CONCURRENT_ACTIVITIES} concurrent activities allowed")

    if activity_type == "crafting":
        if not parameters.get("recipe_id"):
            errors.append("recipe_id is required for crafting")
        required_materials = parameters.get("required_materials", [])
        inventory = {item.get("id"): item for item in player_data.get("inventory", [])}
        for mat_id in required_materials:
            if mat_id not in inventory:
                errors.append(f"Missing required material: {mat_id}")

    elif activity_type == "training":
        if not parameters.get("program_id"):
            errors.append("program_id is required for training")

    elif activity_type == "companion_errand":
        errand_type = parameters.get("errand_type")
        if errand_type not in VALID_ERRAND_TYPES:
            errors.append(f"Invalid errand type: {errand_type}")
        if not parameters.get("destination"):
            errors.append("destination is required for companion errands")

    return ValidationResult(valid=len(errors) == 0, errors=errors)


# --- Resolution functions ---


def resolve_crafting(
    player_data: dict,
    parameters: dict,
    rng: random.Random | None = None,
) -> CraftingOutcome:
    """Resolve a crafting activity. Skill check determines outcome tier."""
    r = rng or random.Random()

    # Skill check for crafting
    craft_skill = parameters.get("skill", "arcana")
    dc = parameters.get("dc", 13)
    mod = skill_modifier(player_data, craft_skill)
    d20 = r.randint(1, 20)
    total = d20 + mod
    margin = total - dc

    required_materials = parameters.get("required_materials", [])
    recipe_id = parameters.get("recipe_id", "unknown")
    result_item_id = parameters.get("result_item_id", recipe_id)
    result_item_name = parameters.get("result_item_name", "crafted item")

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


def resolve_training(
    player_data: dict,
    parameters: dict,
    rng: random.Random | None = None,
) -> TrainingOutcome:
    """Resolve a training activity. Determines stat gains and breakthroughs."""
    r = rng or random.Random()

    training_stat = parameters.get("stat", "strength")
    training_skill = parameters.get("skill")
    dc = parameters.get("dc", 13)

    # Roll for training outcome
    d20 = r.randint(1, 20)
    base_mod = attribute_modifier(player_data.get("attributes", {}).get(training_stat, 10))
    total = d20 + base_mod
    margin = total - dc

    stat_gains: dict = {}
    ability_unlocked = None

    if d20 == 20 or margin >= 5:
        tier = "breakthrough"
        stat_gains = {"skill_bonus": training_skill} if training_skill else {training_stat: 1}
        # Small chance to unlock ability on nat 20
        if d20 == 20 and parameters.get("potential_ability"):
            ability_unlocked = parameters["potential_ability"]
        decisions = [
            {"id": "continue", "label": "Continue pushing your limits"},
            {"id": "rest", "label": "Rest and consolidate what you've learned"},
        ]
    elif margin >= -2:
        tier = "plateau"
        stat_gains = {"skill_familiarity": training_skill} if training_skill else {"training_progress": training_stat}
        decisions = [
            {"id": "persist", "label": "Keep training the same way"},
            {"id": "change_approach", "label": "Try a different approach"},
        ]
    else:
        tier = "redirection"
        # Discover something different
        alt_stat = r.choice([s for s in ("strength", "dexterity", "wisdom", "intelligence") if s != training_stat])
        stat_gains = {"insight": alt_stat}
        decisions = [
            {"id": "follow_insight", "label": f"Explore the insight about {alt_stat}"},
            {"id": "refocus", "label": f"Refocus on {training_stat}"},
        ]

    narrative_context = {
        "tier": tier,
        "roll": d20,
        "total": total,
        "dc": dc,
        "training_stat": training_stat,
        "training_skill": training_skill,
        "mentor_id": parameters.get("mentor_id", "guildmaster_torin"),
    }

    return TrainingOutcome(
        tier=tier,
        stat_gains=stat_gains,
        ability_unlocked=ability_unlocked,
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
