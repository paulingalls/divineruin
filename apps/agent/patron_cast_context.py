"""Transaction-local patron predicates from the caster, targets and lifetime map history."""

import json
from dataclasses import dataclass

from condition_produce import resolve_effective_targets
from spell_voice_rules import is_area_spell


@dataclass(frozen=True)
class PatronCastFacts:
    is_concealed: bool = False
    target_wronged_caster: bool = False
    targets_at_zero_hp: bool = False
    first_stay: bool = False


async def resolve_facts(
    patron,
    session,
    player,
    *,
    conn,
    queries_mod,
    spell,
    combat_state=None,
    target_id=None,
    target_ids=None,
    is_concealed=False,
    target_wronged_caster=False,
) -> PatronCastFacts:
    at_zero = False
    first_stay = False
    if patron == "mortaen" and (target_id is not None or target_ids):
        targets = resolve_effective_targets(target_ids, target_id, self_value=None)
        state = combat_state if combat_state is not None else session.combat_state
        hit_points = []
        for target in targets:
            if state is not None:
                participant = next((p for p in state.participants if p.id == target), None)
                hp = participant.hp_current if participant is not None else None
            else:
                row = player if target == player["player_id"] else await queries_mod.get_player(target, conn=conn)
                hp = (row.get("hp") or {}).get("current") if row is not None else None
            hit_points.append(hp)
        at_zero = bool(hit_points) and all(type(hp) is int and hp == 0 for hp in hit_points)
    if patron == "nythera":
        row = await conn.fetchrow(
            "SELECT data FROM player_map_progress WHERE player_id = $1 AND location_id = $2",
            player["player_id"],
            session.location_id,
        )
        if row is not None:
            data = row["data"]
            if isinstance(data, str):
                data = json.loads(data)
            first_stay = not data.get("revisited", False)
    # These two facts are supplied by syrath-valdris-producers; absence never establishes them.
    return PatronCastFacts(
        is_concealed,
        target_wronged_caster and target_id is not None and target_ids is None and not is_area_spell(spell.id),
        at_zero,
        first_stay,
    )
