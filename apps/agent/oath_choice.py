"""Issue derived oath offers and register them under the encounter and player locks."""

import json
from uuid import uuid4

from livekit.agents import ToolError

from combat_state import CombatState
from oath_breach import BROKEN_REASON, suppressed
from oaths import (
    JUSTICE_NAME,
    JUSTICE_TERMS,
    TIMED_NAME,
    TIMED_TERMS,
    JusticeOath,
    OathBook,
    ObjectiveInput,
    TimedOath,
    deadline_is_current,
    receipt,
)
from session_data import SessionData

PREFIX = "oath_"


def _offer(actor: str, player: dict, state: CombatState | None, count: int) -> dict:
    if player.get("class") != "paladin":
        raise ToolError("Only a paladin can swear a registered oath.")
    patron = (player.get("divine_favor") or {}).get("patron")
    if patron == "valdris":
        if suppressed(player):
            raise ToolError(BROKEN_REASON)
        return {
            "choice_id": f"{PREFIX}{actor}_justice_{count}",
            "resolve_with": "select",
            "options": ["justice"],
            "name": JUSTICE_NAME,
            "scope": "player",
            "term_descriptions": {"justice": list(JUSTICE_TERMS.values())},
        }
    if patron != "zhael":
        raise ToolError("Your patron offers no registered oath.")
    if state is None:
        raise ToolError("Swear a timed oath during combat.")
    speaker = state.get_participant(actor)
    if speaker is None or speaker.type != "player":
        raise ToolError("Swear a timed oath while participating in the encounter.")
    if speaker.is_dead or speaker.hp_current <= 0:
        raise ToolError("Swear a timed oath while above 0 HP.")
    targets: dict[str, list[str]] = {objective: [] for objective in TIMED_TERMS}
    for participant in state.participants:
        # The holder cannot be their own ally: keeping yourself standing would earn the save bonus for free.
        if participant.id == actor or participant.is_structure or participant.is_dead or participant.hp_current <= 0:
            continue
        objective = "keep_ally_standing" if participant.is_ally else "defeat_target"
        targets[objective].append(participant.id)
    return {
        "choice_id": f"{PREFIX}{actor}_timed_{state.combat_id}_{count}",
        "resolve_with": "select",
        "options": ["timed"],
        "name": TIMED_NAME,
        "scope": "encounter",
        "combat_id": state.combat_id,
        "round_number": state.round_number,
        "min_last_round": state.round_number,
        "objective_kinds": list(TIMED_TERMS),
        "eligible_targets": targets,
        "term_descriptions": TIMED_TERMS,
    }


def offer(session: SessionData, actor: str, player: dict | None) -> dict | None:
    session.validate_acting_player(actor)
    if player is None:
        return None
    book = OathBook.from_player(player, actor)
    if any(record.status == "active" for record in book.records):
        return None
    try:
        return _offer(actor, player, session.combat_state, len(book.records))
    except ToolError:
        return None


async def select(
    session: SessionData,
    actor: str,
    choice_id: str,
    option: str,
    objective_kind: ObjectiveInput,
    target_id: str,
    last_round: int,
    *,
    db_mod,
    queries_mod,
) -> str:
    async with session.combat_state_lock, db_mod.transaction() as conn:
        players = await queries_mod.get_players_for_update([actor], conn=conn)
        player = players.get(actor)
        if player is None:
            raise ToolError(f"Unknown player: {actor}.")
        book = OathBook.from_player(player, actor)
        for record in book.records:
            if record.choice_id == choice_id:
                expected = (
                    (record.kind, record.objective_kind, record.target_id, record.last_round)
                    if isinstance(record, TimedOath)
                    else (record.kind, "none", "", 0)
                )
                if (option, objective_kind, target_id, last_round) != expected:
                    raise ToolError("This oath choice already recorded a different selection.")
                session.validate_acting_player(actor)
                return json.dumps(receipt(record))
        if any(record.status == "active" for record in book.records):
            raise ToolError("An active oath already binds you.")
        current = _offer(actor, player, session.combat_state, len(book.records))
        if choice_id != current["choice_id"]:
            raise ToolError("This oath choice ID was not offered to you for this scope.")
        if option not in current["options"]:
            raise ToolError("That oath option was not offered.")
        if option == "timed":
            if not deadline_is_current(last_round, current["min_last_round"]):
                raise ToolError("The last round must be at or after the current round.")
            if target_id not in current["eligible_targets"][objective_kind]:
                target_type = "living hostile" if objective_kind == "defeat_target" else "standing ally"
                raise ToolError(f"Choose an offered {target_type} for this oath.")
        fields = {
            "id": f"oath_{uuid4().hex}",
            "owner_id": actor,
            "choice_id": choice_id,
            "status": "active",
            "latest_state_change_event_id": f"oath_event_{uuid4().hex}",
        }
        if option == "justice":
            record = JusticeOath.model_validate(
                {**fields, "kind": "justice", "patron": "valdris", "terms": list(JUSTICE_TERMS), "bound_entity_ids": []}
            )
        else:
            record = TimedOath.model_validate(
                {
                    **fields,
                    "kind": "timed",
                    "patron": "zhael",
                    "combat_id": current["combat_id"],
                    "round_number": current["round_number"],
                    "last_round": last_round,
                    "objective_kind": objective_kind,
                    "target_id": target_id,
                    "terms": [objective_kind],
                    "bound_entity_ids": [target_id],
                }
            )
        book.records.append(record)
        session.validate_acting_player(actor)
        await conn.execute(
            "UPDATE players SET data = jsonb_set(data, '{oaths}', $2::jsonb) WHERE player_id = $1",
            actor,
            book.model_dump_json(exclude_none=True),
        )
        return json.dumps(receipt(record))
