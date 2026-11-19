"""Executable contracts for the Still's free and zone actions."""

import re

STILL_ZONE_KINDS = ("rejection", "final_stillness")
STILL_ACTION_KINDS = (*STILL_ZONE_KINDS, "illusion")
STILL_FIELDS = ("auto_hit", "minimum_destroyed_anchors", "check_skill")


def validate_still_action(action, path, kind, invalid, positive, validate_recharge):
    if "auto_hit" in action and (
        action["auto_hit"] is not True
        or kind != "attack"
        or action.get("type") != "melee"
        or type(action.get("to_hit")) is not int
        or action["to_hit"] != 0
        or not isinstance(action.get("damage"), str)
        or not re.fullmatch(r"[1-9][0-9]*d[1-9][0-9]*(?:[+-][0-9]+)?", action["damage"])
        or not isinstance(action.get("damage_type"), str)
        or not action["damage_type"]
        or not positive(action.get("reach"))
        or action.get("applies_condition") != "charmed"
        or action.get("save") != "WIS"
        or not positive(action.get("dc"))
        or any(key in action for key in ("resolution", "half_on_success", "duration", "advantage"))
    ):
        invalid(f"{path}.auto_hit")
    for key, carrier in (("minimum_destroyed_anchors", "final_stillness"), ("check_skill", "illusion")):
        if key in action and kind != carrier:
            invalid(f"{path}.{key}")
    if kind not in STILL_ACTION_KINDS:
        return
    fields = {
        "rejection": ("save", "radius_ft"),
        "final_stillness": ("save", "minimum_destroyed_anchors", "duration_dice"),
        "illusion": ("check_skill",),
    }
    allowed = {"kind", "name", "description", "narration_cue", "audio", "properties", "recharge", "dc", *fields[kind]}
    for key in action.keys() - allowed:
        invalid(f"{path}.{key}")
    if not positive(action.get("dc")):
        invalid(f"{path}.dc")
    if kind in STILL_ZONE_KINDS and action.get("save") != "WIS":
        invalid(f"{path}.save")
    if kind == "rejection" and not positive(action.get("radius_ft")):
        invalid(f"{path}.radius_ft")
    if kind == "final_stillness":
        threshold = action.get("minimum_destroyed_anchors")
        if not positive(threshold) or threshold > 6:
            invalid(f"{path}.minimum_destroyed_anchors")
        if not isinstance(action.get("duration_dice"), str) or not re.fullmatch(
            r"1d[1-9][0-9]*", action["duration_dice"]
        ):
            invalid(f"{path}.duration_dice")
    if kind == "illusion" and action.get("check_skill") != "investigation":
        invalid(f"{path}.check_skill")
    recharge = action.get("recharge")
    validate_recharge(recharge, f"{path}.recharge")
    expected = {"rejection": "roll", "final_stillness": "encounter", "illusion": "round"}
    if recharge["kind"] != expected[kind] or (kind != "rejection" and recharge["uses"] != 1):
        invalid(f"{path}.recharge")
