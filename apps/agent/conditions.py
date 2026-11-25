"""Apply, validate, tick, and aggregate JSON-native combat conditions."""

from condition_catalog import (
    CONDITION_CATALOG as CONDITION_CATALOG,
)
from condition_catalog import INCORPOREAL, MARK_OF_JUSTICE
from condition_catalog import (
    BonusDie as BonusDie,
)
from condition_catalog import (
    ConditionEffects as ConditionEffects,
)
from condition_catalog import (
    ConditionSpec as ConditionSpec,
)

_HOLLOWED_MAX_STAGE = 3


def assert_known_condition(name: str, ctx: str) -> None:
    """Fail-loud if ``name`` is not a known condition type (``CONDITION_CATALOG``).

    ``ctx`` prefixes the error to name the offending row — e.g. ``f"spell {spell_id!r}"``,
    ``f"ability {ability_id!r}"``, or ``f"enemy {eid!r} action {aname!r}"``. This is the ONE
    shared ``applies_condition`` strict-load guard for the spell / ability / encounter loaders,
    which each carried a byte-identical inline check. The message format is preserved verbatim so
    callers and their tests are unchanged.
    """
    if name not in CONDITION_CATALOG:
        raise ValueError(f"{ctx} applies_condition {name!r} is not a known condition")


def validate_condition_dict(c: object) -> dict:
    """Fail-loud validation for one stored condition dict (M4.4 story-005, JSONB read boundary).

    A condition round-trips through JSONB as {type, duration, source, stacks?|stage?}. Checks the
    closed-vocab ``type`` against CONDITION_CATALOG and the int-typed fields WHEN PRESENT (``stacks``
    / ``stage`` are int; ``duration`` is int|None) — well-formed dicts vary by condition, so absent
    fields are fine. Returns ``c`` on success; raises ValueError on a corrupt dict so a bad row
    surfaces at the boundary instead of crashing a downstream resolver."""
    if not isinstance(c, dict):
        raise ValueError(f"condition entry is not a dict: {c!r}")
    if "type" not in c:
        raise ValueError(f"condition dict missing 'type': {c!r}")
    ctype = c["type"]
    if ctype not in CONDITION_CATALOG:
        raise ValueError(f"unknown condition type: {ctype!r}")
    for int_field in ("stacks", "stage"):
        if int_field in c and not isinstance(c[int_field], int):
            raise ValueError(f"condition {ctype!r} {int_field} must be an int, got {c[int_field]!r}")
    if "duration" in c and c["duration"] is not None and not isinstance(c["duration"], int):
        raise ValueError(f"condition {ctype!r} duration must be int or None, got {c['duration']!r}")
    from condition_sources import charm_sources

    charm_sources([c])
    return c


def validate_conditions(conditions: list) -> list:
    """Validate every entry of a stored conditions list (fail-loud); returns it on success."""
    for c in conditions:
        validate_condition_dict(c)
    return conditions


def cap_exhaustion(conditions: list[dict], cap: int) -> list[dict]:
    """Return a new list with the ``exhausted`` entry's ``stacks`` clamped to ``cap`` (M4.4
    story-005). No-op when no exhausted entry is present or it is already at/below ``cap``. Never
    mutates the input. Used at the combat-START load boundary to enforce the iron-constitution cap
    (the in-scope apply site until a forced-march/travel producer ships)."""
    result = [dict(c) for c in conditions]
    existing = _find(result, "exhausted")
    if existing is not None and existing.get("stacks", 0) > cap:
        existing["stacks"] = cap
    return result


def _find(conditions: list[dict], condition_type: str) -> dict | None:
    """Return the active instance of ``condition_type``, or None."""
    for c in conditions:
        if c["type"] == condition_type:
            return c
    return None


def has_condition(conditions: list[dict], condition_type: str) -> bool:
    """True when ``condition_type`` is active in the list. Lets a producer confirm an
    ``apply_condition`` actually landed (it no-ops under the immunity gate)."""
    return _find(conditions, condition_type) is not None


def damage_hp_floor(active_conditions: list[dict] | tuple[dict, ...]) -> int:
    return int(any(condition["type"] == INCORPOREAL for condition in active_conditions))


def apply_condition(
    conditions: list[dict],
    condition_type: str,
    *,
    duration: int | None = None,
    source: str | None = None,
    max_stacks: int | None = None,
    originating_participant_id: str | None = None,
    inspire_attack_upgrade: bool = False,
) -> list[dict]:
    """Return a new condition list with ``condition_type`` applied.

    Stackable conditions (Exhausted) increment ``stacks`` up to the effective cap
    (``max_stacks`` override, else the catalog's ``default_max_stacks``) rather than
    duplicating. Hollowed escalates its ``stage`` (capped at 3). Other re-applies of
    an already-active condition refresh its duration/source. Mark of Justice matches
    by source as well as type. Never mutates the input.
    Raises ``ValueError`` on an unknown condition type (fail-loud).
    """
    spec = CONDITION_CATALOG.get(condition_type)
    if spec is None:
        raise ValueError(f"Unknown condition type: {condition_type!r}")

    result = [dict(c) for c in conditions]

    # Immunity gate (M4.4 story-008): if any active condition makes its bearer immune to
    # ``condition_type``, applying it is a no-op (e.g. a Temporary Hollowed shrugs off Charmed).
    if any(condition_type in CONDITION_CATALOG[c["type"]].immunities for c in result):
        return result

    existing = next(
        (
            c
            for c in result
            if c["type"] == condition_type and (condition_type != MARK_OF_JUSTICE or c.get("source") == source)
        ),
        None,
    )
    applied = {"type": condition_type, "duration": duration, "source": source}
    if condition_type == "inspired":
        applied["inspire_attack_upgrade"] = inspire_attack_upgrade
    if originating_participant_id is not None:
        applied["originating_participant_id"] = originating_participant_id

    if condition_type == "hollowed":
        if existing is not None:
            existing["stage"] = min(existing["stage"] + 1, _HOLLOWED_MAX_STAGE)
            return result
        result.append({**applied, "stage": 1})
        return result

    if spec.stackable:
        cap = max_stacks if max_stacks is not None else spec.default_max_stacks
        if existing is not None:
            existing["stacks"] = min(existing["stacks"] + 1, cap) if cap is not None else existing["stacks"] + 1
            return result
        result.append({**applied, "stacks": 1})
        return result

    if existing is not None:
        if condition_type == "charmed":
            existing.pop("choir_melody", None)
        existing.update(applied)
        return result

    result.append({**applied, "stacks": 1})
    return result


def remove_condition(conditions: list[dict], condition_type: str) -> list[dict]:
    """Return a new condition list with every instance of ``condition_type`` removed.
    Other conditions are untouched; never mutates the input."""
    return [dict(c) for c in conditions if c["type"] != condition_type]


def remove_conditions(conditions: list[dict], condition_types: tuple[str, ...]) -> list[dict]:
    """Return a new condition list with every instance of each type in ``condition_types`` removed.

    The plural fold for consume-on-use (M4.8 story-003): a roll can spend more than one beneficial
    die (a bearer who is both Blessed and Inspired), so remove the whole consumed set in one pass.
    No-op (a fresh copy) when ``condition_types`` is empty. Never mutates the input."""
    drop = set(condition_types)
    return [dict(c) for c in conditions if c["type"] not in drop]


def hollowed_stage(conditions: list[dict] | None) -> int:
    """Return the active Hollowed stage (1-3), or 0 when not Hollowed (M4.4 story-008).

    Tolerates a JSON-null ``conditions`` (players.data.conditions can be stored null) by treating
    it as no conditions. The combat-engine rise check reads this to gate the Temporary Hollowed
    on Stage 2+."""
    existing = _find(conditions or [], "hollowed")
    return existing["stage"] if existing is not None else 0


def tick_conditions(conditions: list[dict]) -> tuple[list[dict], list[dict]]:
    """Advance conditions one phase. Return ``(survivors, save_events)``.

    Integer durations decrement; conditions hitting 0 are dropped. ``None`` durations
    persist until explicitly cleared. Conditions whose catalog spec names a recurring
    ``tick_save`` (Frightened and Paralyzed) surface a save event so the wrap
    caller (story-002) can resolve the save-to-clear — this module only *signals* it,
    it never rolls. Never mutates the input.
    """
    survivors: list[dict] = []
    save_events: list[dict] = []
    for c in conditions:
        spec = CONDITION_CATALOG[c["type"]]
        if spec.tick_save is not None:
            event = {"type": c["type"], "save": spec.tick_save, "source": c.get("source")}
            if "originating_participant_id" in c:
                event["originating_participant_id"] = c["originating_participant_id"]
            save_events.append(event)

        duration = c["duration"]
        if duration is None:
            survivors.append(dict(c))
            continue
        remaining = duration - 1
        if remaining <= 0:
            continue
        ticked = dict(c)
        ticked["duration"] = remaining
        survivors.append(ticked)
    return survivors, save_events


def _hollowed_effects(stage: int) -> tuple[set[str], set[str]]:
    """Return (disadvantage_scopes, restrictions) for a Hollowed instance at ``stage``.
    Stage 1 = disadvantage WIS; stage 2 adds hallucinations; stage 3 adds stat drain."""
    disadvantage = {"wis"}
    restrictions: set[str] = set()
    if stage >= 2:
        restrictions.add("hallucinations")
    if stage >= 3:
        restrictions.add("stat_drain")
    return disadvantage, restrictions


def get_condition_effects(conditions: list[dict]) -> ConditionEffects:
    """Aggregate every active condition into the read model resolvers consume.

    Numeric modifiers sum (Exhausted's per-stack penalty scales with ``stacks``);
    scope/restriction/save sets union. Hollowed contributes stage-distinct effects.
    """
    check_modifier = 0
    ac_modifier = 0
    damage_modifier = 0
    disadvantage: set[str] = set()
    advantage: set[str] = set()
    auto_fail: set[str] = set()
    restrictions: set[str] = set()
    immunities: set[str] = set()
    bonus_damage_dice: str | None = None
    bonus_damage_type: str | None = None
    bonus_dice: list[BonusDie] = []

    for c in conditions:
        spec = CONDITION_CATALOG[c["type"]]
        immunities.update(spec.immunities)
        # At most one active condition grants a rider die today (the Temporary Hollowed), so a
        # scalar last-wins assignment is exact; revisit if two riders ever co-exist.
        if spec.bonus_damage_dice is not None:
            bonus_damage_dice = spec.bonus_damage_dice
            bonus_damage_type = spec.bonus_damage_type
        # Beneficial bonus die (M4.8): surfaced per-condition (consumed-on-use needs the source), so
        # a bearer who is both Blessed and Inspired yields two dice — no silent last-wins drop.
        if spec.bonus_die is not None:
            bonus_dice.append(
                BonusDie(
                    source=c["type"],
                    dice=spec.bonus_die,
                    scopes=frozenset(spec.bonus_die_scopes),
                    inspire_attack_upgrade=c.get("inspire_attack_upgrade", False) if c["type"] == "inspired" else False,
                )
            )
        if c["type"] == "hollowed":
            hol_dis, hol_res = _hollowed_effects(c["stage"])
            disadvantage |= hol_dis
            restrictions |= hol_res
            continue
        stacks = c.get("stacks", 1)
        check_modifier += spec.check_modifier * stacks
        ac_modifier += spec.ac_modifier
        damage_modifier += spec.damage_modifier
        disadvantage.update(spec.disadvantage_scopes)
        advantage.update(spec.advantage_scopes)
        auto_fail.update(spec.auto_fail_saves)
        restrictions.update(spec.restrictions)

    return ConditionEffects(
        check_modifier=check_modifier,
        ac_modifier=ac_modifier,
        damage_modifier=damage_modifier,
        disadvantage_scopes=frozenset(disadvantage),
        advantage_scopes=frozenset(advantage),
        auto_fail_saves=frozenset(auto_fail),
        restrictions=frozenset(restrictions),
        bonus_damage_dice=bonus_damage_dice,
        bonus_damage_type=bonus_damage_type,
        immunities=frozenset(immunities),
        bonus_dice=tuple(bonus_dice),
    )
