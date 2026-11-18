"""Durable patron gift activation and authored rest recharge."""

import json

from livekit.agents.llm import ToolError

import check_discovery
import concealment
import db
import db_mutations_conditions
import db_mutations_skill_advancement
import db_queries
from check_skill import _check_skill_run
from condition_consume import serialize_combat_check
from patron_gifts import KNOWLEDGE_SKILLS, SYRATH_SHADOW_VEIL, VEYTHAR_INSIGHT, syrath_gift, veythar_gift
from quest_progress import lock_discovery_rows
from skill_check_effects import SkillCheckEffects


def gift_state(player):
    namespace = player.get("patron_gifts", {})
    if not isinstance(namespace, dict):
        raise ValueError("Malformed patron_gifts")
    if VEYTHAR_INSIGHT not in namespace:
        return {"spent": False, "pending": None}
    state = namespace[VEYTHAR_INSIGHT]
    if not isinstance(state, dict) or set(state) != {"spent", "pending"} or type(state["spent"]) is not bool:
        raise ValueError("Malformed Lorekeeper's Insight state")
    pending = state["pending"]
    if pending is not None:
        if (
            not isinstance(pending, dict)
            or pending.get("kind") not in {"skill", "discover"}
            or pending.get("skill") not in KNOWLEDGE_SKILLS
            or type(pending.get("dc")) is not int
            or not isinstance(pending.get("location_id"), str)
            or type(pending.get("hearing_only")) is not bool
        ):
            raise ValueError("Malformed Lorekeeper's Insight pending check")
        fields = ("difficulty", "context_description") if pending["kind"] == "skill" else ("target",)
        if any(not isinstance(pending.get(key), str) for key in fields):
            raise ValueError("Malformed Lorekeeper's Insight check context")
        if pending["kind"] == "discover" and (
            "element_id" not in pending
            or (pending["element_id"] is not None and not isinstance(pending["element_id"], str))
        ):
            raise ValueError("Malformed Lorekeeper's Insight discovery context")
    if state["spent"] and pending is not None:
        raise ValueError("Spent Lorekeeper's Insight has a pending check")
    return state


async def write_state(player_id, state, *, gift_id, conn):
    await conn.execute(
        """UPDATE players SET data=jsonb_set(
            jsonb_set(data, '{patron_gifts}', COALESCE(data->'patron_gifts','{}'::jsonb)),
            ARRAY['patron_gifts',$2], $3::jsonb) WHERE player_id=$1""",
        player_id,
        gift_id,
        json.dumps(state),
    )


async def offer(session, player, result, pending, *, conn):
    if result.auto_fail or result.success or result.skill.lower() not in KNOWLEDGE_SKILLS:
        return None
    gift = veythar_gift(player)
    if gift is None or gift_state(player)["spent"]:
        return None
    session.validate_acting_player(session.acting_player_id)
    await write_state(
        session.acting_player_id, {"spent": False, "pending": pending}, gift_id=VEYTHAR_INSIGHT, conn=conn
    )
    return f'{gift["name"]}: optionally invoke activate(id="{gift["id"]}") to reroll. Take the new result.'


async def recharge(player_id, player, rest_type, *, conn):
    from _gods_content import load_gods
    from patron_ability_tools import spent_state

    patron_id = (player.get("divine_favor") or {}).get("patron")
    patron = next((p for p in load_gods() if p["god_id"] == patron_id), None)
    if patron is None:
        return
    recharges = {"short_rest", "long_rest"} if rest_type == "long" else {f"{rest_type}_rest"}
    uses = [patron["layer_1_gift"], *patron["layer_3_tier_abilities"].values()]
    for use in uses:
        if use["recharge"] not in recharges:
            continue
        ability_id = use["id"]
        if ability_id == VEYTHAR_INSIGHT:
            state, default = gift_state(player), {"spent": False, "pending": None}
        else:
            state, default = spent_state(player, ability_id), {"spent": False}
        if state != default:
            await write_state(player_id, default, gift_id=ability_id, conn=conn)


@serialize_combat_check
async def activate_insight(context):
    import check_tools

    session = context.userdata
    effects = SkillCheckEffects()
    async with db.transaction() as conn:
        # Quest locks precede player locks even if a concurrent check replaces the offer kind.
        player = await lock_discovery_rows(session, conn=conn)
        if veythar_gift(player) is None:
            raise ToolError("Lorekeeper's Insight requires an active Veythar gift.")
        state = gift_state(player)
        if state["spent"]:
            raise ToolError("Lorekeeper's Insight is spent. Take a short rest to restore it.")
        pending = state["pending"]
        if pending is None:
            raise ToolError("Lorekeeper's Insight has no failed check to reroll.")
        session.validate_acting_player(session.acting_player_id)
        await write_state(
            session.acting_player_id, {"spent": True, "pending": None}, gift_id=VEYTHAR_INSIGHT, conn=conn
        )
        if pending["kind"] == "skill":
            response = await _check_skill_run(
                context,
                pending["skill"],
                pending["difficulty"],
                pending["context_description"],
                hearing_only=pending["hearing_only"],
                queries=db_queries,
                mutations=db_mutations_skill_advancement,
                db_mod=db,
                conditions_mutations=db_mutations_conditions,
                effects=effects,
                conn=conn,
                locked_player=player,
                reroll_dc=pending["dc"],
            )
        else:
            response, discovery_effects = await check_discovery.reroll_discovery(context, player, pending, conn=conn)
    if pending["kind"] == "skill":
        await effects.flush(session, publish=check_tools.publish_game_event)
    else:
        await discovery_effects()
    return response if isinstance(response, str) else json.dumps(response)


def shadow_veil_state(player):
    namespace = player.get("patron_gifts", {})
    if not isinstance(namespace, dict):
        raise ValueError("Malformed patron_gifts")
    state = namespace.get(SYRATH_SHADOW_VEIL, {"spent": False})
    if not isinstance(state, dict) or set(state) != {"spent"} or type(state["spent"]) is not bool:
        raise ValueError("Malformed Shadow Veil state")
    return state


@serialize_combat_check
async def activate_shadow_veil(context):
    session = context.userdata
    state = session.combat_state
    if state is None:
        raise ToolError("Shadow Veil is combat-only. It lasts until the current round ends.")
    player_id = session.acting_player_id
    participant = state.get_participant(player_id)
    if participant is None or participant.type != "player":
        raise ToolError("Shadow Veil requires a current player combat participant.")
    async with db.transaction() as conn:
        player = await db_queries.get_player(player_id, conn=conn, for_update=True)
        if player is None:
            raise ToolError(f"Player '{player_id}' not found")
        if syrath_gift(player) is None:
            raise ToolError("Shadow Veil requires an active Syrath gift.")
        if shadow_veil_state(player)["spent"]:
            raise ToolError("Shadow Veil is spent. Take a short rest to restore it.")
        concealment.gift_lifetime(player)
        if concealment.is_concealed(player):
            raise ToolError("Already hidden. Shadow Veil remains available.")
        session.validate_acting_player(player_id)
        await write_state(player_id, {"spent": True}, gift_id=SYRATH_SHADOW_VEIL, conn=conn)
        packet = await concealment.transition(player, True, lifetime=True, conn=conn)
    return json.dumps({"concealment": packet, "expires_round": state.round_number})
