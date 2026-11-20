"""One declaration's attack summary, aggregated across the swings of an expanded sequence."""


def aggregate(attack_summaries: list[dict], *, moved: bool) -> dict:
    summary = dict(attack_summaries[0])
    last = None
    if len(attack_summaries) > 1:
        # Report the expansion: per-attack detail under "attacks", flat keys aggregated.
        # Damage/hit/critical/concentration accumulate across swings; the target-state keys
        # (hp_status, fallen) must reflect the FINAL swing — the kill on the second hit, not
        # the goblin-still-up snapshot from the first — or the DM narrates a fallen foe alive.
        summary["attacks"] = attack_summaries
        last = next(s for s in reversed(attack_summaries) if "target_hp_status" in s)
    # A follow-up after a wall collapses has a different recipient and keeps its own damage and HP status.
    if last is not None and last["target"] == summary["target"]:
        summary.pop("unholy_fortitude", None)
        for component in ("bonus_damage", "rider_damage", "synergy_damage"):
            summary[component] = sum(s.get(component, 0) for s in attack_summaries)
            type_key = f"{component}_type"
            summary[type_key] = next((s[type_key] for s in attack_summaries if s.get(type_key) is not None), None)
        if moved:
            summary.update(
                moved_ft=sum(s["moved_ft"] for s in attack_summaries),
                closed_distance=any(s["closed_distance"] for s in attack_summaries),
                destination=attack_summaries[-1]["destination"],
            )
        summary["damage"] = sum(s.get("damage", 0) for s in attack_summaries)
        summary["hit"] = any(s.get("hit", False) for s in attack_summaries)
        summary["critical"] = any(s.get("critical", False) for s in attack_summaries)
        summary["target_hp_status"] = last["target_hp_status"]
        summary["target_fallen"] = last["target_fallen"]
        summary["concentration_broken"] = next(
            (s["concentration_broken"] for s in attack_summaries if s.get("concentration_broken")), None
        )
        # Any swing being dramatic makes the declaration dramatic. Each swing rolls its
        # own d20 and runs its own killing-blow check, so a later swing can be dramatic
        # while the first is routine — take the FIRST dramatic swing's context so the
        # aggregated dramatic flag and its reason label never disagree (story-004).
        summary["dramatic"] = any(s.get("dramatic", False) for s in attack_summaries)
        summary["context"] = next((s["context"] for s in attack_summaries if s.get("dramatic")), "")
    return summary
