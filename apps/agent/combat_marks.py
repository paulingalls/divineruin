"""Round-scoped focus marks created by enemy social actions."""

MARK_KINDS = frozenset({"command", "accusation"})
FOCUS_ATTACK_BONUS = 2


def resolve_mark_action(state, source, target, kind: str) -> None:
    if kind not in MARK_KINDS:
        raise ValueError(f"action kind {kind!r} does not create a focus mark")
    state.focus_marks[target.id] = {"source_id": source.id, "kind": kind}


def attack_bonus(state, attacker, target) -> int:
    mark = state.focus_marks.get(target.id)
    if mark is None:
        return 0
    if not isinstance(mark, dict) or set(mark) != {"source_id", "kind"}:
        raise ValueError(f"malformed focus mark for {target.id!r}: {mark!r}")
    source_id, kind = mark["source_id"], mark["kind"]
    if not isinstance(source_id, str) or kind not in MARK_KINDS:
        raise ValueError(f"malformed focus mark for {target.id!r}: {mark!r}")
    source = state.get_participant(source_id)
    if source is None:
        raise ValueError(f"focus mark for {target.id!r} names missing source {source_id!r}")
    if attacker.is_fallen or attacker.is_dead or attacker.id == source.id or attacker.is_ally != source.is_ally:
        return 0
    return FOCUS_ATTACK_BONUS
