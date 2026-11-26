"""Resolve Song of Rest against the locked party and their recovered pools."""

import asyncpg
from livekit.agents.llm import ToolError

import abilities
import ability_persistence
import mentor_variants
from ability_voice_rules import require_ability_delivery
from communication_voice_rules import DeliveryRefused, can_hear
from dice import roll

SONG_OF_REST = "bard_song_of_rest"

Recovery = tuple[int | None, int | None, int]


async def apply_song_of_rest(
    players: dict[str, dict],
    recovery: dict[str, Recovery],
    max_hp: dict[str, int],
    remote_ids: list[str],
    *,
    conn: asyncpg.Connection,
) -> dict:
    ability = abilities.get_ability(SONG_OF_REST)
    resting_ids = sorted(players)
    hearing_ids = [pid for pid in resting_ids if can_hear(None, pid, rows=players)]
    refusal = "No resting member has learned Song of Rest."
    for singer in resting_ids:
        player = players[singer]
        owns_elective = await ability_persistence.owns_elective(singer, SONG_OF_REST, conn=conn)
        if not abilities.owns_ability(player["class"], player["level"], ability, owns_elective=owns_elective):
            continue
        variant_id = await ability_persistence.get_active_variant(singer, SONG_OF_REST, conn=conn)
        source = mentor_variants.get_variant(SONG_OF_REST, variant_id) if variant_id is not None else ability
        cost = source.cost.focus
        stamina, focus, hp = recovery[singer]
        if focus is None:
            raise ValueError(f"Song of Rest requires a Focus pool for {singer}")
        if focus < cost:
            refusal = "No resting singer has enough Focus after recovery for Song of Rest."
            continue
        try:
            require_ability_delivery(SONG_OF_REST, None, singer, hearing_ids, rows=players)
        except DeliveryRefused as exc:
            refusal = str(exc)
            continue
        recovery[singer] = stamina, focus - cost, hp
        break
    else:
        raise ToolError(refusal)

    healing = []
    skipped = [{"player_id": pid, "reason": "not_at_rest_location"} for pid in remote_ids]
    for pid in resting_ids:
        if pid not in hearing_ids:
            skipped.append({"player_id": pid, "reason": "cannot_hear"})
            continue
        stamina, focus, before = recovery[pid]
        rolled = roll("1d8").total
        after = min(max_hp[pid], before + rolled)
        recovery[pid] = stamina, focus, after
        healing.append(
            {"player_id": pid, "roll": rolled, "hp_before": before, "hp_after": after, "healed": after - before}
        )

    return {
        "ability_id": SONG_OF_REST,
        "singer_id": singer,
        "singer_name": player["name"],
        "variant_id": variant_id,
        "focus_paid": cost,
        "narration_cue": source.narration_cue,
        "healing": healing,
        "skipped": skipped,
    }
