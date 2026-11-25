"""Persisted encounter facts used by combat synergies."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from livekit.agents.llm import ToolError

import ability_persistence
from check_resolution_attack import AttackResult
from combat_down import DEATH_SAVE_LIMIT
from patron_synergy import has_engine_synergy

if TYPE_CHECKING:
    from asyncpg import Connection

    from combat_damage_results import AutomaticDamageResult, SaveDamageResult
    from combat_participant import CombatParticipant
    from combat_state import CombatState

MORTAEN_RENEWAL = "mortaen_death_feeds_renewal"
ZHAEL_THREADED_BLADE = "zhael_threaded_blade"


ZHAEL_RALLY = "zhael_moment_to_rally"


class EncounterFacts(TypedDict):
    ally_downers: list[str]
    attacked: list[str]
    death_save_success_round: dict[str, int]
    misses: dict[str, list[str]]
    once_spent: dict[str, list[str]]
    party_aggressors: dict[str, list[str]] | None
    rally_pending: dict[str, str]


def empty() -> EncounterFacts:
    return {
        "ally_downers": [],
        "attacked": [],
        "death_save_success_round": {},
        "misses": {},
        "once_spent": {},
        "party_aggressors": {},
        "rally_pending": {},
    }


def upgrade_legacy_snapshot(snapshot: dict) -> dict:
    if "encounter_facts" in snapshot:
        return snapshot
    facts = empty()
    facts["party_aggressors"] = None
    return {**snapshot, "encounter_facts": facts}


def _is_id(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _ids(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(_is_id(item) for item in value):
        raise ValueError(f"encounter_facts.{field} requires a list of nonblank string IDs")
    return list(value)


def _id_map(value: object, field: str) -> dict[str, list[str]]:
    if not isinstance(value, dict) or not all(_is_id(key) for key in value):
        raise ValueError(f"encounter_facts.{field} requires an object keyed by nonblank string IDs")
    return {key: _ids(ids, f"{field}.{key}") for key, ids in value.items()}


def _death_save_rounds(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("encounter_facts.death_save_success_round requires an object")
    for participant_id, round_number in value.items():
        if not _is_id(participant_id) or type(round_number) is not int or round_number < 1:
            raise ValueError(
                "encounter_facts.death_save_success_round requires nonblank IDs and positive integer rounds"
            )
    return dict(value)


def validate_history(value: object) -> dict[str, list[str]] | None:
    return None if value is None else _id_map(value, "party_aggressors")


def validate(value: object) -> EncounterFacts:
    current = EncounterFacts.__required_keys__
    previous = current - {"rally_pending"}
    prior = previous - {"party_aggressors"}
    if not isinstance(value, dict) or value.keys() not in (current, previous, prior):
        raise ValueError(f"encounter_facts requires {', '.join(sorted(prior))} and a supported snapshot shape")
    history = value.get("party_aggressors")
    spent = _id_map(value["once_spent"], "once_spent")
    pending = value.get("rally_pending", {})
    if not isinstance(pending, dict) or not all(_is_id(source) and _is_id(ally) for source, ally in pending.items()):
        raise ValueError("encounter_facts.rally_pending requires a map of nonblank string IDs")
    if not pending.keys() <= set(spent.get(ZHAEL_RALLY, [])):
        raise ValueError("encounter_facts.rally_pending requires each source to have spent its rally")
    return {
        "ally_downers": _ids(value["ally_downers"], "ally_downers"),
        "attacked": _ids(value["attacked"], "attacked"),
        "death_save_success_round": _death_save_rounds(value["death_save_success_round"]),
        "misses": _id_map(value["misses"], "misses"),
        "once_spent": spent,
        "rally_pending": dict(pending),
        "party_aggressors": validate_history(history),
    }


def _remember(ids: list[str], participant_id: str) -> None:
    if participant_id not in ids:
        ids.append(participant_id)


def record_party_attack(state: CombatState | None, attacker: CombatParticipant, target: CombatParticipant) -> None:
    if state is None or attacker.is_ally or not target.is_ally:
        return
    history = state.encounter_facts["party_aggressors"]
    if history is not None:
        _remember(history.setdefault(attacker.id, []), target.id)


def party_victims(state: CombatState, hostile_id: str) -> list[str]:
    history = state.encounter_facts["party_aggressors"]
    if history is None:
        raise ToolError("This encounter's party aggression history is unknown.")
    return list(history.get(hostile_id, ()))


def has_attacked_party(state: CombatState, hostile_id: str) -> bool:
    return bool(party_victims(state, hostile_id))


def record_landing(
    state: CombatState | None,
    attacker: CombatParticipant,
    target: CombatParticipant,
    result: AttackResult | SaveDamageResult | AutomaticDamageResult,
    hp_before: int,
) -> None:
    if state is None:
        return
    facts = state.encounter_facts
    if attacker.id != target.id and hp_before > 0 and target.is_ally and target.is_fallen:
        _remember(facts["ally_downers"], attacker.id)
    if isinstance(result, AttackResult):
        _remember(facts["attacked"], target.id)
        # Threaded Blade reads a foe; missing masonry must not arm its one use.
        if not result.hit and not target.is_structure:
            _remember(facts["misses"].setdefault(attacker.id, []), target.id)
        if result.synergy_clause_id == ZHAEL_THREADED_BLADE:
            _remember(facts["once_spent"].setdefault(ZHAEL_THREADED_BLADE, []), attacker.id)


def counted_death(target: CombatParticipant) -> bool:
    # A destroyed wall is marked dead but is no creature, so "when a creature dies" never counts it.
    return not target.is_structure and (
        target.is_dead
        or (target.type != "companion" and target.death_save_failures >= DEATH_SAVE_LIMIT)
        or (not target.is_ally and target.hp_current == 0)
    )


async def renew_on_death(
    state: CombatState | None,
    target: CombatParticipant,
    counted_before: bool,
    *,
    queries,
    conn: Connection | None,
) -> list[dict]:
    if state is None or counted_before or not counted_death(target):
        return []

    receipts = []
    for recipient in sorted(state.participants, key=lambda p: p.id):
        if recipient.type != "player" or recipient.is_fallen:
            continue
        if conn is None or not conn.is_in_transaction():
            raise ValueError("Death Feeds Renewal requires the combat transaction")
        player = await queries.get_player(recipient.id, for_update=True, conn=conn)
        if player is None:
            raise ValueError(f"Missing authoritative player {recipient.id!r}")
        if not has_engine_synergy(player, MORTAEN_RENEWAL):
            continue
        pool = player["focus"]
        current, maximum = pool["current"], pool["max"]
        renewed = min(maximum, current + 2)
        await ability_persistence.update_player_resources(recipient.id, focus=renewed, conn=conn)
        receipts.append(
            {
                "clause_id": MORTAEN_RENEWAL,
                "player_id": recipient.id,
                "deceased_id": target.id,
                "focus_regained": renewed - current,
                "focus_current": renewed,
                "focus_max": maximum,
            }
        )
    return receipts
