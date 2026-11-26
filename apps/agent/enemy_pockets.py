"""Initialize enemy item drops in the caller's combat transaction."""

from __future__ import annotations

from copy import deepcopy
from random import Random
from typing import TYPE_CHECKING

import asyncpg

import db_content_queries
import db_queries
import encounter_loot
from combat_participant import CombatParticipant
from rules_engine import SKILL_TIER_ORDER, SKILLS, SkillTier, _get_skill_tier

if TYPE_CHECKING:
    from combat_state import CombatState


async def _best_skill_tiers(state: CombatState, *, conn: asyncpg.Connection, queries) -> dict[str, SkillTier]:
    tiers: dict[str, SkillTier] = dict.fromkeys(SKILLS, "untrained")
    for participant in state.participants:
        if participant.type != "player":
            continue
        player = await queries.get_player(participant.id, conn=conn)
        if player is None:
            continue
        for skill, best in tiers.items():
            tier = _get_skill_tier(player, skill)
            if SKILL_TIER_ORDER.index(tier) > SKILL_TIER_ORDER.index(best):
                tiers[skill] = tier
    return tiers


async def initialize(
    state: CombatState, *, conn: asyncpg.Connection, queries=db_queries, content=db_content_queries
) -> None:
    enemies = {p.id: p for p in state.participants if p.type == "enemy"}
    missing_images = []
    for checkpoint in state.round_checkpoints:
        for row in checkpoint["combat"]["participants"]:
            if row["type"] != "enemy" or row.get("carried_items") is not None:
                continue
            missing_images.append(row)
            if row["id"] not in enemies:
                enemies[row["id"]] = CombatParticipant(**row)

    pending = [enemy for enemy in enemies.values() if enemy.carried_items is None]
    if pending:
        tables = {
            table_id: await content.get_loot_table(table_id)
            for table_id in dict.fromkeys(enemy.loot_table_id for enemy in pending if enemy.loot_table_id)
        }
        tiers = (
            await _best_skill_tiers(state, conn=conn, queries=queries)
            if any(table is not None for table in tables.values())
            else {}
        )
        rng = Random()
        for enemy in pending:
            table = tables.get(enemy.loot_table_id)
            enemy.carried_items = (
                [
                    {**drop, "tainted": table.get("hollow_residue", False)}
                    for drop in encounter_loot.generate_loot(table, enemy.role, tiers, rng)
                ]
                if table is not None
                else []
            )
    for row in missing_images:
        row["carried_items"] = deepcopy(enemies[row["id"]].carried_items)
