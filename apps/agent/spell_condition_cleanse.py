"""Greater Restoration target validation and transaction-bound condition removal."""

from dataclasses import dataclass
from typing import Literal

from livekit.agents.llm import ToolError

import combat_spell_heal
import db_mutations_conditions
import hollowed_progression
import still_charm
from combat_participant import CombatParticipant
from combat_state import CombatState
from conditions import remove_condition
from declarations import Declaration, resolve_declaration
from session_data import SessionData

GREATER_RESTORATION = "divine_greater_restoration"
CleanseCondition = Literal["charmed", "petrified"]
NAME = "Greater Restoration"


class CleanseRefused(ToolError):
    """The target became ineligible before the cast wrote anything."""


def single_target(caster_id: str, target_id: str | None, target_ids: list[str] | None) -> str:
    if target_ids is not None:
        raise ValueError(f"{NAME} targets one player. Use target_id or omit it for self.")
    return target_id if target_id is not None else caster_id


def combat_target(
    state: CombatState, caster_id: str, target_id: str | None, target_ids: list[str] | None
) -> CombatParticipant:
    pid = single_target(caster_id, target_id, target_ids)
    target = combat_spell_heal.combat_ally(state, pid, NAME)
    if target.type != "player":
        raise ValueError(f"{NAME} requires a player participant: {pid}")
    return target


def _select(active: set[str], choice: str | None) -> str:
    if "hollowed" in active:
        if choice not in (None, "hollowed"):
            raise CleanseRefused(f"{NAME} removes Hollowed first. Choose Hollowed or omit the choice.")
        return "hollowed"
    eligible = active & {"charmed", "petrified"}
    if not eligible:
        raise CleanseRefused(f"{NAME} requires a target with Hollowed, Charmed or Petrified.")
    if choice is not None:
        if choice not in eligible:
            raise CleanseRefused(f"{NAME} cannot remove {choice} from this target. Choose a present condition.")
        return choice
    if len(eligible) > 1:
        raise CleanseRefused(f"{NAME}: choose Charmed or Petrified.")
    return eligible.pop()


@dataclass
class Cleanse:
    target_id: str
    row: dict
    participant: CombatParticipant | None
    condition: str

    async def land(self, *, conn, queries) -> dict:
        row, pid, removed = self.row, self.target_id, self.condition
        durable = row.get("conditions") or []
        restored = 0
        if removed == "hollowed":
            stored = next((c for c in durable if c["type"] == "hollowed"), None)
            live = (
                next((c for c in self.participant.conditions if c["type"] == "hollowed"), None)
                if self.participant
                else None
            )
            hollowed = {**(live or {}), **(stored or {})}
            active = [*remove_condition(durable, "hollowed"), hollowed]
            if not await hollowed_progression.cleanse_hollowed(pid, {**row, "conditions": active}, conn=conn):
                raise RuntimeError(f"Expected Hollowed on {pid} during the cleanse")
            after = await queries.get_player(pid, conn=conn)
            if after is None:
                raise RuntimeError(f"Missing locked cleanse recipient {pid}")
            wisdom = after["attributes"]["wisdom"]
            restored = wisdom - row["attributes"]["wisdom"]
            if self.participant is not None and restored:
                self.participant.attributes["wisdom"] = wisdom
        else:
            await db_mutations_conditions.save_player_conditions(pid, remove_condition(durable, removed), conn=conn)
            if removed == "charmed":
                await still_charm.clear([pid], row["location_id"], conn=conn)

        if self.participant is not None:
            self.participant.conditions = remove_condition(self.participant.conditions, removed)
        name = row.get("name") or pid
        cue = f"Greater Restoration removes {removed.capitalize()} from {name}."
        if restored:
            cue += f" {name} regains {restored} Wisdom."
        return {
            "target_id": pid,
            "target_name": name,
            "condition_removed": removed,
            "wisdom_restored": restored,
            "narration_cue": cue,
        }


def _prepare(pid: str, row: dict, participant: CombatParticipant | None, choice: str | None) -> Cleanse:
    active = {c["type"] for c in row.get("conditions") or []}
    if participant is not None:
        active.update(c["type"] for c in participant.conditions)
    if still_charm.read(row, pid, row["location_id"]) is not None:
        active.add("charmed")
    return Cleanse(pid, row, participant, _select(active, choice))


def exploration_target(pid: str, caster_row: dict, rows: dict[str, dict], choice: str | None) -> Cleanse:
    row = rows.get(pid)
    if row is None or row["location_id"] != caster_row["location_id"]:
        raise CleanseRefused(f"{NAME} requires a present party player: {pid}")
    return _prepare(pid, row, None, choice)


async def prepare_combat(
    session: SessionData,
    state: CombatState,
    caster_id: str,
    declaration: Declaration,
    *,
    queries,
    conn=None,
    lock: bool = False,
) -> Cleanse:
    try:
        target = combat_target(state, caster_id, declaration.target_id, declaration.target_ids)
    except ValueError as e:
        raise CleanseRefused(str(e)) from e
    if target.id not in session.party.member_ids:
        raise CleanseRefused(f"{NAME} requires a party player: {target.id}")
    if lock:
        row = (await queries.get_players_for_update([target.id], conn=conn)).get(target.id)
    else:
        row = await queries.get_player(target.id, conn=conn)
    if row is None:
        raise CleanseRefused(f"{NAME} requires a durable player: {target.id}")
    return _prepare(target.id, row, target, declaration.argument_type or None)


async def preflight_declarations(session: SessionData, state: CombatState, *, queries) -> None:
    for caster_id, raw in state.pending_declarations.items():
        if raw.get("action") == GREATER_RESTORATION:
            await prepare_combat(session, state, caster_id, resolve_declaration(raw), queries=queries)
