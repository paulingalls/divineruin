"""Round-scoped focus marks created by enemy social actions."""

MARK_KINDS = frozenset({"command", "accusation"})
FOCUS_ATTACK_BONUS = 2


def resolve_mark_action(state, source, target, kind: str, *, cancelled: bool = False) -> dict:
    """Apply a hostile mark; the returned dict is the packet's account of what was applied.

    A CANCELLED mark is the one branch that reports ``resolved`` without writing a row: the
    reaction that cancelled it carries the verdict (command_countered/accusation_dismissed) on
    its own packet, so the DM already has the reason and a second refusal would double it.
    """
    if kind not in MARK_KINDS:
        raise ValueError(f"action kind {kind!r} does not create a focus mark")
    resolved = {"resolved": True, "kind": kind}
    if cancelled:
        return resolved
    current_source = _mark_source(state, target)
    if current_source is None:
        state.focus_marks[target.id] = {"source_id": source.id, "kind": kind}
        return resolved
    if current_source.is_ally == source.is_ally:
        return {"resolved": False, "reason": f"{target.name}'s focus mark is held by {current_source.name}"}
    raise ValueError(f"focus mark for {target.id!r} belongs to {current_source.id!r}, not {source.id!r}")


def _mark_source(state, target):
    mark = state.focus_marks.get(target.id)
    if mark is None:
        return None
    if not isinstance(mark, dict) or set(mark) != {"source_id", "kind"}:
        raise ValueError(f"malformed focus mark for {target.id!r}: {mark!r}")
    source_id, kind = mark["source_id"], mark["kind"]
    if not isinstance(source_id, str) or kind not in MARK_KINDS:
        raise ValueError(f"malformed focus mark for {target.id!r}: {mark!r}")
    source = state.get_participant(source_id)
    if source is None:
        raise ValueError(f"focus mark for {target.id!r} names missing source {source_id!r}")
    return source


def attack_bonus(state, attacker, target) -> int:
    source = _mark_source(state, target)
    if source is None:
        return 0
    if (
        attacker.is_fallen
        or attacker.is_dead
        or source.is_fallen
        or source.is_dead
        or attacker.id == source.id
        or attacker.is_ally != source.is_ally
    ):
        return 0
    return FOCUS_ATTACK_BONUS
