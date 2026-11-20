"""Authored patron uses: derived eligibility, durable spend and shared projection."""

import json

from livekit.agents.llm import ToolError

import db
import db_mutations
import db_queries
import event_types as E
import patron_combat_edges
from _gods_content import load_gods
from combat_ui_update import build_combat_ui_update
from game_events import publish_game_event
from patron_favor import get_patron_tier

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
        return ability, updated, response

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
    return ability, updated, response


async def activate(
    context, ability_id, *, target_id=None, condition: str | None = None, destination: dict | None = None
):
    from patron_ability_events import publish_patron_abilities

    session = context.userdata
    actor = session.acting_player_id
    async with session.combat_state_lock:
        async with db.transaction() as conn:
            ability, updated, response = await _spend_activation(
                conn, session, actor, ability_id, target_id, condition, destination
            )
        if updated is not None:
            session.combat_state = updated
            await publish_game_event(
                session.room, E.COMBAT_UI_UPDATE, build_combat_ui_update(updated), event_bus=session.event_bus
            )
        await publish_patron_abilities(session.room, actor, session.event_bus)
    return json.dumps(
        {
            "id": ability_id,
            "name": ability["name"],
            "effect": ability["effect"],
            "recharge": ability["recharge"],
            "dm_cue": "Narrate the authored answer or effect. Obtain mechanical facts from engine/query tools "
            'before stating any number; for enemy AC use query_info(kind="creature", target_id=<enemy id>). '
            "Never invent an unavailable number.",
            **response,
        }
    )
