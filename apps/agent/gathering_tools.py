"""Gathering resolution for the `check` verb's mode="gather" (M4.6c / story-003).

`_check_gather_impl` is the IO half of gathering: it reads the player's current location, rolls
the gating skill (Survival/Nature/Arcana by material category), drives the pure `gathering`
engine, grants the harvested materials, consumes a fixed gathering_node on a rich find (marks it
discovered + depletes its quantity), emits a DICE_ROLL, and returns a narration cue. It lives
here (imported by check_tools.py's dispatcher) the same way mode="social" lives in social_tools.py
— keeping the check verb lean. Resolution math is reused unchanged from gathering.py /
check_resolution.py; this module only does the plumbing + IO.
"""

import json
import logging
import random

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import check_resolution
import db
import db_content_queries
import db_mutations
import db_mutations_conditions
import db_mutations_gathering
import db_queries
import event_types as E
import gathering
import rules_engine
from condition_consume import consume_beneficial_conditions
from db_errors import validated_player_conditions
from game_events import publish_game_event
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")

# Per-region gathering DC (spec §Regional Resource Tables, L1008-1018). Apply-site config: the
# pure gathering.resolve_gathering takes the DC injected, so the region→DC mapping lives here,
# not in the resolver. Fail-loud on an unmapped region (a content/caller bug).
REGION_GATHERING_DC: dict[str, int] = {
    "greyvale": 10,
    "thornveld": 12,
    "drathian_steppe": 12,
    "sunward_coast": 12,
    "keldaran_mountains": 14,
    "ashmark": 16,
    "underground": 16,
}


async def _check_gather_impl(
    context: RunContext[SessionData],
    material_type: str,
    *,
    queries=db_queries,
    mutations=db_mutations,
    content=db_content_queries,
    gather_mutations=db_mutations_gathering,
    conditions_mutations=db_mutations_conditions,
    db_mod=db,
    rng: random.Random | None = None,
) -> str:
    logger.info("check gather: material_type=%r", material_type)
    session: SessionData = context.userdata
    player = await queries.get_player(session.player_id)
    if player is None:
        raise ToolError(f"Player '{session.player_id}' not found.")
    # Read-boundary guard (M4.4 story-008): a corrupt conditions row becomes a DM-narratable error.
    validated_player_conditions(player, session.player_id)

    location = await content.get_location(session.location_id)
    if location is None:
        raise ToolError(f"Current location '{session.location_id}' not found.")
    resource_table_raw = location.get("resource_table")
    nodes = [n for n in await content.get_gathering_nodes_at_location(session.location_id) if n.get("quantity", 0) > 0]
    if not resource_table_raw and not nodes:
        raise ToolError("Nothing to forage here.")

    mat = material_type or None
    try:
        skill = gathering.gathering_skill(mat)
    except ValueError as e:
        raise ToolError(str(e)) from e
    skill_tier = rules_engine._get_skill_tier(player, skill)

    region = location.get("region")
    dc = REGION_GATHERING_DC.get(region)
    if dc is None:
        raise ToolError(f"No gathering DC for region {region!r}.")

    roll = check_resolution.resolve_skill_check_dc(player, skill, dc, rng)
    resource_table = {rarity: tuple(ids) for rarity, ids in (resource_table_raw or {}).items()}
    result = gathering.resolve_gathering(
        material_type=mat,
        skill_tier=skill_tier,
        gathering_dc=dc,
        roll_total=roll.total,
        resource_table=resource_table,
        raw_die=roll.roll,
    )

    # A rich find reveals + harvests one fixed node (discovery is margin-only, decision
    # gathering-discovery-margin-only). The node is matched to the rolled skill so foraging for
    # herbs surfaces the herb garden, not an unrelated ore vein (falls back to any node if none
    # match). Gives the gathering_nodes table its live reader/writer. select_node is pure.
    node = gathering.select_node(nodes, skill) if result.discovery else None
    granted = list(result.materials)
    node_revealed = None
    if node is not None:
        granted.append(node["resource_type"])
        node_revealed = node["id"]

    counts: dict[str, int] = {}
    for material_id in granted:
        counts[material_id] = counts.get(material_id, 0) + 1

    # One transaction so the gather commits atomically: a partial write (node depleted but
    # materials not granted, or granted without depletion) would dupe or lose items in the
    # persistent economy. The conn= seams on both mutation modules thread the tx connection.
    async with db_mod.transaction() as conn:
        if node is not None:
            await gather_mutations.mark_node_discovered(node["id"], conn=conn)
            await gather_mutations.deplete_node_quantity(node["id"], 1, conn=conn)
        for material_id, qty in counts.items():
            await mutations.add_inventory_item(session.player_id, material_id, qty, conn=conn)
        # The gather roll spends Blessed/Inspired's +1d4 (M4.8 story-009): remove + persist the
        # signalled conditions on the SAME tx connection, so the die-consume commits atomically
        # with the node depletion + inventory grant. No-op when nothing was consumed.
        await consume_beneficial_conditions(
            session.player_id, roll.consumed_conditions, conditions_mutations, conn=conn
        )

    success = result.result != "nothing"
    await publish_game_event(
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "gathering_check",
            "skill": skill,
            "roll": roll.roll,
            "total": roll.total,
            "success": success,
            "dramatic": result.dramatic,
            "context": result.context,
        },
        event_bus=session.event_bus,
    )

    session.record_event(f"Gather ({skill}): {result.narrative_cue}")
    return json.dumps(
        {
            "outcome": "success" if success else "failure",
            "result": result.result,
            "skill": skill,
            "materials": granted,
            "discovery": result.discovery,
            "node_revealed": node_revealed,
            "time_cost": result.time_cost,
            "dramatic": result.dramatic,
            "context": result.context,
            "narrative_cue": result.narrative_cue,
            "roll": roll.roll,
            "total": roll.total,
            "dc": result.dc,
            "margin": result.margin,
        }
    )
