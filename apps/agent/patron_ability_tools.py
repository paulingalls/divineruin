"""Authored patron uses: derived eligibility, durable spend and shared projection."""

import json
from typing import TYPE_CHECKING

import asyncpg
from livekit.agents.llm import ToolError

import db
import db_mutations
import db_queries
import event_types as E
import patron_combat_edges
from _gods_content import load_gods
from combat_state import CombatState
from combat_ui_update import build_combat_ui_update
from game_events import publish_game_event
from patron_favor import get_patron_tier
from patron_passives import effective_hp

if TYPE_CHECKING:
    from session_data import SessionData

TIERS = ("Acknowledged", "Devoted", "Exalted")
LUCKY = "zhael_lucky"
WEIGHT_OF_TRUTH = "valdris_weight_of_truth"
_REST = {"short_rest": "a short rest", "long_rest": "a long rest", "per_session": "a new session"}


def catalog():
    return {
        ability["id"]: (patron["god_id"], tier, ability)
        for patron in load_gods()
        for tier in TIERS
        for ability in [patron["layer_3_tier_abilities"][tier.lower()]]
    }


def spent_state(player, ability_id):
    namespace = player.get("patron_gifts", {})
    if not isinstance(namespace, dict):
        raise ValueError("Malformed patron_gifts")
    state = namespace.get(ability_id, {"spent": False})
    if not isinstance(state, dict) or set(state) != {"spent"} or type(state["spent"]) is not bool:
        raise ValueError(f"Malformed patron ability state: {ability_id}")
    return state


def availability(ability, tier, required, spent):
    if required is not None and TIERS.index(tier) < TIERS.index(required):
        return f"Requires {required} tier.", "locked"
    resolution = ability.get("resolution", "narrated")
    implemented = resolution == "narrated" or (
        resolution == "engine" and ability.get("implementation_id") == ability["id"]
    )
    if ability["status"] != "active" or not implemented:
        return "This ability is pending implementation.", "locked"
    if ability["recharge"] == "always":
        return "This ability is always-on; it cannot be activated.", "locked"
    if spent:
        return f"Already spent; requires {_REST[ability['recharge']]} to restore it.", "spent"
    return None, "ready"


def blocking_reason(ability, tier, required, spent):
    return availability(ability, tier, required, spent)[0]


def lucky_ready(player, ability):
    favor = player.get("divine_favor") or {}
    return (
        ability["id"] == LUCKY
        and favor.get("patron") == "zhael"
        and blocking_reason(ability, get_patron_tier(favor), "Acknowledged", spent_state(player, LUCKY)["spent"])
        is None
    )


def project_abilities(player, patron):
    tier = get_patron_tier(player["divine_favor"])
    if tier is None:
        return []
    rows = []
    for required in TIERS:
        ability = patron["layer_3_tier_abilities"][required.lower()]
        spent = spent_state(player, ability["id"])["spent"]
        reason, state = availability(ability, tier, required, spent)
        rows.append(
            {
                **{key: ability[key] for key in ("id", "name", "recharge", "status")},
                "tier": required,
                "eligible": TIERS.index(tier) >= TIERS.index(required),
                "spent": spent,
                "available": reason is None,
                "reason": reason,
                "state": state,
            }
        )
    return rows


async def _locked_ability(conn, actor, ability_id):
    if ability_id == WEIGHT_OF_TRUTH:
        patron_id, required = "valdris", None
        ability = next(p["layer_1_gift"] for p in load_gods() if p["god_id"] == patron_id)
    else:
        patron_id, required, ability = catalog()[ability_id]
    player = await db_queries.get_player(actor, conn=conn, for_update=True)
    if player is None:
        raise ToolError(f"Player {actor!r} not found.")
    favor = player.get("divine_favor")
    if favor is None:
        raise ToolError("Cannot activate: no patron or divine_favor row.")
    if (favor.get("patron") or "none") == "none":
        raise ToolError("Cannot activate patron abilities: Unbound.")
    tier = get_patron_tier(favor)
    if favor["patron"] != patron_id:
        raise ToolError(f"This ability requires a follower of {patron_id}.")
    reason = blocking_reason(ability, tier, required, spent_state(player, ability_id)["spent"])
    if reason:
        raise ToolError(reason)
    return ability


async def _write_spend(conn, session, actor, ability_id):
    from patron_gift_tools import write_state

    try:
        session.validate_acting_player(actor)
    except (RuntimeError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    await write_state(actor, {"spent": True}, gift_id=ability_id, conn=conn)


async def spend(session, actor, ability_id):
    async with db.transaction() as conn:
        ability = await _locked_ability(conn, actor, ability_id)
        await _write_spend(conn, session, actor, ability_id)
    return ability


def _shield_target(session: "SessionData", actor: str, target: str | None) -> str:
    if target is None:
        raise ToolError("Community Shield requires a target_id.")
    if target == actor:
        raise ToolError("Community Shield targets another player.")
    if target not in session.present_member_ids:
        raise ToolError("Community Shield requires a present party player.")
    return target


async def _prepare_shield(
    conn: asyncpg.Connection, session: "SessionData", actor: str, target_id: str | None
) -> tuple[dict, CombatState | None, dict, dict | None]:
    ability_id = patron_combat_edges.COMMUNITY_SHIELD
    try:
        target = _shield_target(session, actor, target_id)
    except ToolError:
        # Keep patron refusals ahead of selector errors without locking a second row out of order.
        await _locked_ability(conn, actor, ability_id)
        raise
    players = await db_queries.get_players_for_update([actor, target], conn=conn)
    ability = await _locked_ability(conn, actor, ability_id)
    if target not in players:
        raise ToolError(f"Player {target!r} not found.")
    if target not in session.present_member_ids:
        raise ToolError("Community Shield requires a present party player.")
    updated, response = await patron_combat_edges.community_shield(
        session.combat_state, actor, target, players[actor], players[target], conn=conn
    )
    health = {**effective_hp(players[target]), "temp_hp": response["temp_hp"]} if updated is None else None
    return ability, updated, response, health


async def _spend_activation(conn, session, actor, ability_id, target_id, condition, destination: dict | None):
    if ability_id == patron_combat_edges.RESTORATION_SURGE:
        target = target_id or actor
        if target != actor and target not in session.present_member_ids:
            raise ToolError("Restoration Surge requires a present party member as its target.")
        players = await db_queries.get_players_for_update([actor, target], conn=conn)
        if target not in players:
            raise ToolError(f"Player {target!r} not found.")
        ability = await _locked_ability(conn, actor, ability_id)
        updated, response = await patron_combat_edges.restoration_surge(
            session.combat_state, actor, target, condition, players[target], conn=conn
        )
        await _write_spend(conn, session, actor, ability_id)
        return ability, updated, response, None

    health = None
    if ability_id == patron_combat_edges.COMMUNITY_SHIELD:
        ability, updated, response, health = await _prepare_shield(conn, session, actor, target_id)
    else:
        ability = await _locked_ability(conn, actor, ability_id)
        updated = None
        response = {}
        if ability.get("resolution") == "engine":
            handler = patron_combat_edges.ACTIVE_GIFTS.get(ability_id)
            if handler is None:
                raise ToolError("This ability cannot be activated directly.")
            selector = (
                {"destination": destination} if ability_id == patron_combat_edges.VEILSTEP else {"target_id": target_id}
            )
            updated, response = handler(session.combat_state, actor, **selector)
    await _write_spend(conn, session, actor, ability_id)
    if updated is not None:
        await db_mutations.save_combat_state(updated.combat_id, updated.to_dict(), conn=conn)
    return ability, updated, response, health


async def _activate_wrath(session: "SessionData", actor: str, ability_id: str) -> tuple[dict, dict, tuple | None]:
    import lost_scout_combat
    from attribute_increase_events import publish_snapshots
    from combat_end import _end_combat_db, _end_combat_finish
    from combat_events import EventSink, isolated_publish, scratch_guard
    from combat_hollow_resonance import take_totals
    from combat_phase import combat_outcome
    from patron_ability_events import publish_patron_abilities
    from patron_zero_hp import lock_damage_players
    from resonance_events import publish_resonance_changed
    from thyra_wrath import wildmothers_wrath

    sink = EventSink()
    end_data = None
    async with scratch_guard(session), db.transaction() as conn:
        await lock_damage_players(session, None, queries=db_queries, conn=conn)
        ability = await _locked_ability(conn, actor, ability_id)
        updated, response = await wildmothers_wrath(session, actor, conn=conn, sink=sink)
        totals = take_totals(updated)
        await _write_spend(conn, session, actor, ability_id)
        outcome = combat_outcome(updated)
        if outcome is None:
            await db_mutations.save_combat_state(updated.combat_id, updated.to_dict(), conn=conn)
        else:
            residue = await lost_scout_combat.residue(
                session, updated, mutations=db_mutations, queries=db_queries, conn=conn
            )
            end_data = await _end_combat_db(
                session, updated, outcome, mutations=db_mutations, queries=db_queries, conn=conn, sink=sink
            )
            if residue is not None:
                end_data["lost_scout_residue"] = residue

    handoff = None
    if outcome is None:
        session.combat_state = updated
    else:
        assert end_data is not None
        handoff = _end_combat_finish(session, updated, outcome, end_data)
    for member in session.party.members:
        if member.player_id in totals:
            member.resonance.current = totals[member.player_id]

    if end_data is not None:
        with isolated_publish("Wildmother's Wrath level snapshots"):
            await publish_snapshots(session, end_data["level_up_recipients"])
    with isolated_publish("Wildmother's Wrath events"):
        await sink.flush()
    if handoff is None:
        with isolated_publish("Wildmother's Wrath combat update"):
            await publish_game_event(
                session.room, E.COMBAT_UI_UPDATE, build_combat_ui_update(updated), event_bus=session.event_bus
            )
    with isolated_publish("Wildmother's Wrath patron abilities"):
        await publish_patron_abilities(session.room, actor, session.event_bus)
    for member in session.party.members:
        if member.player_id in totals:
            with isolated_publish(f"Wildmother's Wrath resonance update ({member.player_id})"):
                await publish_resonance_changed(session, resonance_track=member.resonance, caster_id=member.player_id)
    return ability, response, handoff


async def activate(
    context, ability_id, *, target_id=None, condition: str | None = None, destination: dict | None = None
) -> str:
    from combat_events import isolated_publish
    from patron_ability_events import publish_patron_abilities

    session = context.userdata
    actor = session.acting_player_id
    async with session.combat_state_lock:
        async with db.transaction() as conn:
            ability, updated, response, health = await _spend_activation(
                conn, session, actor, ability_id, target_id, condition, destination
            )
        if updated is not None:
            session.combat_state = updated
            await publish_game_event(
                session.room, E.COMBAT_UI_UPDATE, build_combat_ui_update(updated), event_bus=session.event_bus
            )
        if health is not None:
            with isolated_publish("Community Shield HP"):
                await publish_game_event(
                    session.room,
                    E.HP_CHANGED,
                    health,
                    session.event_bus,
                    destination_identities=[response["target_id"]],
                )
        await publish_patron_abilities(session.room, actor, session.event_bus)
    return json.dumps(_activation_response(ability_id, ability, response))


async def activate_wrath(session: "SessionData") -> str | tuple:
    actor = session.acting_player_id
    ability_id = patron_combat_edges.WILDMOTHERS_WRATH
    async with session.combat_state_lock:
        ability, response, handoff = await _activate_wrath(session, actor, ability_id)
    result = _activation_response(ability_id, ability, response)
    if handoff is not None:
        agent, settlement = handoff
        return agent, json.dumps({**json.loads(settlement), **result})
    return json.dumps(result)


def _activation_response(ability_id: str, ability: dict, response: dict) -> dict:
    return {
        "id": ability_id,
        "name": ability["name"],
        "effect": ability["effect"],
        "recharge": ability["recharge"],
        "dm_cue": "Narrate the authored answer or effect. Obtain mechanical facts from engine/query tools "
        'before stating any number; for enemy AC use query_info(kind="creature", target_id=<enemy id>). '
        "Never invent an unavailable number.",
        **response,
    }
