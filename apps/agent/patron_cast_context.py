"""Transaction-local patron predicates from the caster, targets and lifetime map history."""

import json
from dataclasses import dataclass

import cast_modifiers
import combat_wrongdoing
import concealment
from condition_produce import resolve_effective_targets
from spell_voice_rules import is_area_spell


@dataclass(frozen=True)
class PatronCastFacts:
    is_concealed: bool = False
    target_wronged_caster: bool = False
    targets_at_zero_hp: bool = False
    first_stay: bool = False
    wrongdoing: dict | None = None


async def apply_patron(generated: int, standard: int, patron, session, player, *, spell, terrain, **context):
    """Apply the patron's Layer 2 generation; return it with the DM's packet entry when it differs."""
    facts = await _resolve_facts(patron, session, player, spell=spell, **context)
    result, applied = cast_modifiers.apply_patron_generation(generated, spell, patron, terrain=terrain, facts=facts)
    if result == standard:
        return result, None, facts.wrongdoing
    return (
        result,
        {"patron": patron, "applies_to": applied, "standard": standard, "generated": result},
        facts.wrongdoing,
    )


async def _resolve_facts(
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
) -> PatronCastFacts:
    evidence = None
    if patron == "valdris":
        evidence = await combat_wrongdoing.wrongdoing(
            session,
            player,
            target_id=target_id,
            target_ids=target_ids,
            combat_state=combat_state,
            conn=conn,
            queries_mod=queries_mod,
        )
        if target_id is None or target_ids is not None or is_area_spell(spell.id):
            evidence = None
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
    return PatronCastFacts(
        concealment.is_concealed(player),
        evidence is not None,
        at_zero,
        first_stay,
        evidence,
    )
