"""Freeze catalog spell deliveries from participant-anchored combat placement."""

import combat_spatial as spatial
from combat_spell_profile import scaled
from combat_structures import blocked_reason, blocking_wall, chamber_line_blocker, require_line
from condition_sources import DeliveryRefused


def _line_refusal(state, placement, caster_id: str, origin_id: str, target_id: str) -> str | None:
    wall = chamber_line_blocker(state, placement, caster_id, target_id) or blocking_wall(
        state,
        placement,
        spatial.position(placement, origin_id),
        spatial.position(placement, target_id),
        target_id=target_id,
        origin_id=origin_id,
        effect_origin=True,
        physical=False,
    )
    return blocked_reason(wall) if wall is not None else None


def caster_radius_refusal(
    state, placement: dict, caster_id: str, target, radius_ft: int, protected, *, undead_hollow: bool
) -> str | None:
    if target.is_fallen or target.is_dead:
        return "Target is unavailable."
    if target.id in protected:
        return "The Still protects this target."
    if undead_hollow and not (target.hollow or target.category == "undead"):
        return "Target category is neither undead nor Hollow."
    if not spatial.inside(spatial.position(placement, caster_id), spatial.position(placement, target.id), radius_ft):
        return f"Target is beyond {radius_ft} feet."
    return _line_refusal(state, placement, caster_id, caster_id, target.id)


def select(state, caster, declaration, spell, *, require_live=False):
    profile = spell.combat_damage
    ids = list(declaration.target_ids or ([declaration.target_id] if declaration.target_id else []))
    spec = profile.get("recipients")
    if spec is None:
        return [{"target_id": target_id} for target_id in ids]
    # The seed CLI imports validate_spec without gameplay dependencies.
    from still_encounter import protected_ids

    shape = spec["shape"]
    protected = protected_ids(state)
    live = [p for p in state.participants if not p.is_fallen and not p.is_dead and p.id not in protected]
    for target_id in ids:
        target = state.get_participant(target_id)
        if target is None or (require_live and (target.is_fallen or target.is_dead)):
            raise ValueError(f"{spell.name} requires live participant anchors")
    if shape != "caster_radius" and not ids:
        raise ValueError(f"{spell.name} requires a participant anchor")
    if shape == "projectiles":
        count = scaled(profile, "projectile_scaling", profile["projectiles"], caster.level)
        assignments = ids * count if len(ids) == 1 else ids
        if len(assignments) != count:
            raise ValueError(f"{spell.name} requires exactly {count} dart assignments or one recipient")
        for target_id in dict.fromkeys(assignments):
            require_line(state, caster.id, target_id)
        return [
            {
                "target_id": target_id,
                "dart_indices": [i for i, assigned in enumerate(assignments) if assigned == target_id],
            }
            for target_id in dict.fromkeys(assignments)
        ]
    placement = spatial.require_spatial(state)
    for anchor_id in ids:
        if chamber := chamber_line_blocker(state, placement, caster.id, anchor_id):
            raise DeliveryRefused(blocked_reason(chamber))

    def pos(target_id):
        return spatial.position(placement, target_id)

    def clear(origin_id, target_id):
        return _line_refusal(state, placement, caster.id, origin_id, target_id) is None

    if shape == "caster_radius":
        if len(ids) > 1:
            raise ValueError("Too many participant anchors for this area")
        selected = [
            {"target_id": target.id}
            for target in state.participants
            if caster_radius_refusal(
                state,
                placement,
                caster.id,
                target,
                spec["radius_ft"],
                protected,
                undead_hollow=profile.get("restriction") == "undead_hollow",
            )
            is None
        ]
        return sorted(selected, key=lambda delivery: delivery["target_id"] != (ids[0] if ids else None))
    if shape == "chain":
        if len(ids) > spec["cap"] or len(ids) != len(set(ids)):
            raise ValueError("Chain recipients must be unique and within the authored cap")
        primary = ids[0]
        if not any(p.id == primary for p in live):
            return []
        require_line(state, caster.id, primary)
        if len(ids) == 1:
            candidates = sorted(
                (p for p in live if p.id != primary and p.is_ally != caster.is_ally),
                key=lambda p: (spatial.distance(pos(primary), pos(p.id)), p.id),
            )
            ids += [
                p.id
                for p in candidates
                if spatial.inside(pos(primary), pos(p.id), spec["range_ft"]) and clear(primary, p.id)
            ][: spec["cap"] - 1]
        else:
            for target_id in ids[1:]:
                if not spatial.inside(pos(primary), pos(target_id), spec["range_ft"]):
                    raise ValueError("Chain secondary is outside the authored arc range")
                require_line(state, primary, target_id)
        return [{"target_id": target_id, "secondary": i > 0} for i, target_id in enumerate(ids)]
    if len(ids) > spec.get("placements", 1):
        raise ValueError("Too many participant anchors for this area")
    origin = pos(caster.id)
    selected = []
    for target in live:
        point = pos(target.id)
        if profile.get("restriction") == "undead_hollow" and not (target.hollow or target.category == "undead"):
            continue
        if shape == "line":
            covered = spatial.in_line(origin, pos(ids[0]), point, spec["length_ft"], spec["width_ft"]) and clear(
                caster.id, target.id
            )
        elif shape == "cylinder":
            covered = any(
                spatial.inside({**point, "z": pos(anchor)["z"]}, pos(anchor), spec["radius_ft"])
                and pos(anchor)["z"] <= point["z"] <= pos(anchor)["z"] + spec["height_ft"]
                and clear(anchor, target.id)
                for anchor in ids
            )
        else:
            covered = any(
                spatial.inside(pos(anchor), point, spec["radius_ft"]) and clear(anchor, target.id) for anchor in ids
            )
        if covered:
            selected.append({"target_id": target.id})
    return sorted(selected, key=lambda delivery: (delivery["target_id"] != (ids[0] if ids else None),))


def validate_spec(spec):
    fields = {
        "radius": {"radius_ft", "placements"},
        "caster_radius": {"radius_ft"},
        "line": {"length_ft", "width_ft"},
        "cylinder": {"radius_ft", "height_ft", "placements"},
        "chain": {"cap", "range_ft", "secondary_dice"},
        "projectiles": set(),
    }
    if not isinstance(spec, dict) or spec.get("shape") not in fields:
        raise ValueError("invalid spell recipient shape")
    required = fields[spec["shape"]]
    if set(spec) != required | {"shape"}:
        raise ValueError("invalid spell recipient fields")
    for key in required - {"secondary_dice"}:
        value = spatial.number(spec[key], key, nonnegative=True)
        if value <= 0 or (key in {"placements", "cap"} and type(value) is not int):
            raise ValueError("recipient dimensions and caps must be positive")
    if "secondary_dice" in spec:
        from combat_spell_profile import DICE

        if not isinstance(spec["secondary_dice"], str) or not DICE.fullmatch(spec["secondary_dice"]):
            raise ValueError("invalid secondary damage dice")
