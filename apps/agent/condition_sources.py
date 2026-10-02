"""Actor identity for source-bound conditions."""


def charm_sources(active_conditions, participant_ids=None) -> tuple[str, ...]:
    sources = []
    for condition in active_conditions:
        if condition.get("type") != "charmed":
            continue
        source = condition.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Charmed source must be a nonempty actor ID")
        if participant_ids is not None and source not in participant_ids:
            raise ValueError(f"Charmed source {source!r} is not a combat participant")
        sources.append(source)
    return tuple(sources)


def validate_combat_sources(participants) -> None:
    ids = {p["id"] for p in participants}
    for participant in participants:
        charm_sources(participant.get("conditions", []), ids)


def no_hostile_source(active_conditions, *, target_ids, participant_ids, area=False) -> bool:
    sources = charm_sources(active_conditions, participant_ids)
    return bool(sources) and (area or bool(set(sources) & set(target_ids)))


def require_hostile_targets(state, actor, target_ids, *, area=False) -> None:
    if no_hostile_source(
        actor.conditions, target_ids=target_ids, participant_ids={p.id for p in state.participants}, area=area
    ):
        raise ValueError(f"{actor.name} is Charmed and cannot act hostilely against its source")


def clear_charm_from_damage(active_conditions, source_id, damage):
    charm_sources(active_conditions)
    return [
        condition
        for condition in active_conditions
        if not (damage > 0 and condition.get("type") == "charmed" and condition["source"] == source_id)
    ]
