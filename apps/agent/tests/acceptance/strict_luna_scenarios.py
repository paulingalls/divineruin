"""Database and in-memory state for the representative Luna cases."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from acceptance.seeds import seed_player, seed_player_with_pools, seed_training_activity
from sample_fixtures import make_mock_room

import db
import db_mutations
import db_queries
from combat_init import class_reaction_ids
from party_state import PartyState
from session_data import CombatParticipant, CombatState, CreationState, SessionData


@dataclass
class Scenario:
    session_data: SessionData
    before: dict[str, Any] = field(default_factory=dict)


def _player_id(case_id: str) -> str:
    return "luna_" + case_id.replace(".", "_")


async def _player_json(pool, player_id: str) -> dict[str, Any] | None:
    row = await pool.fetchrow("SELECT data FROM players WHERE player_id = $1", player_id)
    return json.loads(row["data"]) if row else None


async def _set_level(pool, player_id: str, level: int) -> None:
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{level}', $2::jsonb) WHERE player_id = $1",
        player_id,
        str(level),
    )


async def _set_skill(pool, player_id: str, skill: str, tier: str) -> None:
    await pool.execute(
        "INSERT INTO skill_advancement (player_id, skill_id, tier, use_counter, narrative_moment_ready) "
        "VALUES ($1, $2, $3, 0, FALSE) ON CONFLICT (player_id, skill_id) DO UPDATE SET tier = $3",
        player_id,
        skill,
        tier,
    )


def _combat_state(player_id: str, case_id: str, *, beat: str = "declaration") -> CombatState:
    enemy_id = "luna_enemy"
    declarations = {}
    if beat == "resolution":
        declarations = {
            player_id: {"type": "attack", "action": "Longsword", "target_id": enemy_id},
            enemy_id: {"type": "defend", "action": "Defend"},
        }
    return CombatState(
        combat_id="combat_" + case_id.replace(".", "_"),
        participants=[
            CombatParticipant(
                id=player_id,
                name="Luna Tester",
                type="player",
                initiative=15,
                hp_current=30,
                hp_max=30,
                ac=15,
                level=6,
                action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
            ),
            CombatParticipant(
                id=enemy_id,
                name="Luna Enemy",
                type="enemy",
                initiative=10,
                hp_current=40,
                hp_max=40,
                ac=12,
                xp_value=25,
                action_pool=[{"name": "Club", "damage": "1d4", "damage_type": "bludgeoning", "properties": []}],
            ),
        ],
        initiative_order=[player_id, enemy_id],
        location_id="accord_guild_hall",
        beat=beat,
        pending_declarations=declarations,
    )


async def _seed_combat(pool, player_id: str, case_id: str, *, beat: str = "declaration") -> CombatState:
    await seed_player_with_pools(pool, player_id=player_id, class_="warrior")
    await _set_level(pool, player_id, 6)
    state = _combat_state(player_id, case_id, beat=beat)
    player = state.get_participant(player_id)
    assert player is not None
    player.reaction_ids = class_reaction_ids("warrior", 6)
    player.has_reaction_ability = bool(player.reaction_ids)
    await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=pool)
    return state


async def prepare_case(case_id: str) -> Scenario:
    pool = await db.get_pool()
    player_id = _player_id(case_id)
    location = "accord_guild_hall"
    if case_id in {"exploration.check_gather", "exploration.travel"}:
        location = "greyvale_south_road"
    if case_id == "blacksmith.repair_item":
        location = "accord_forge"

    if case_id.startswith("combat."):
        beat = "resolution" if case_id == "combat.resolve_phase" else "declaration"
        state = await _seed_combat(pool, player_id, case_id, beat=beat)
        sd = SessionData(player_id=player_id, location_id=location, room=make_mock_room(), combat_state=state)
        if case_id == "combat.activate_reaction":
            import reaction_spend

            state.beat = "narration"
            state.held_actions = [
                {
                    "seq": 0,
                    "actor_id": "luna_enemy",
                    "initiative": 10,
                    "declaration": {"type": "attack", "action": "Club", "target_id": player_id},
                    "roll": {"attack_result": {"hit": True, "damage": 4}},
                    "roll_published": True,
                    "opened": ["post_roll"],
                }
            ]
            state.open_window = {
                "id": "r1-0-post_roll",
                "actor_id": "luna_enemy",
                "target_id": player_id,
                "stage": "post_roll",
                "triggers": ["on_hit"],
                "action_kind": "attack",
            }
            state.reactions_available[player_id] = reaction_spend.unspent()
            await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=pool)
        return Scenario(sd, {"combat_id": state.combat_id, "player": await _player_json(pool, player_id)})

    if case_id.startswith("creation."):
        cs = CreationState()
        if case_id == "creation.finalize_character":
            cs = CreationState(
                phase="identity",
                race="draethar",
                class_choice="warrior",
                deity="none",
                name="Luna Vale",
                backstory="A road-worn guardian.",
            )
        return Scenario(SessionData(player_id=player_id, location_id="", room=make_mock_room(), creation_state=cs))

    class_ = "warrior"
    if case_id in {"exploration.activate_single", "exploration.activate_multiple"}:
        class_ = "bard"
    if case_id == "dispatch.begin_spell_training":
        class_ = "mage"
    await seed_player_with_pools(pool, player_id=player_id, class_=class_)
    sd = SessionData(player_id=player_id, location_id=location, room=make_mock_room())

    if case_id == "exploration.query_inventory":
        await db_mutations.add_inventory_item(player_id, "healing_potion", 2, conn=pool)
    elif case_id == "exploration.check_gather":
        await _set_skill(pool, player_id, "survival", "master")
    elif case_id == "exploration.check_social":
        await _set_skill(pool, player_id, "persuasion", "expert")
    elif case_id == "exploration.check_discover":
        sd.location_id = "accord_market_square"
    elif case_id == "exploration.activate_self":
        await _set_level(pool, player_id, 6)
    elif case_id in {"exploration.activate_single", "exploration.activate_multiple"}:
        level = 9 if case_id.endswith("multiple") else 2
        await _set_level(pool, player_id, level)
        allies = ["luna_target_ally"]
        if case_id.endswith("multiple"):
            allies.append("luna_target_second")
        for ally in allies:
            await seed_player(pool, player_id=ally)
            sd.party.members.append(PartyState.solo(ally).primary)
    elif case_id == "dispatch.resolve_midpoint":
        data = {
            "program_id": "combat_basics",
            "program_name": "Combat Fundamentals",
            "decision_prompt": "Choose your focus.",
            "decision_options": [{"id": "focus_power", "label": "Power"}],
        }
        await seed_training_activity(
            pool,
            activity_id="luna_training",
            player_id=player_id,
            state="awaiting_decision",
            data=data,
        )
    elif case_id == "dispatch.begin_spell_training":
        await _set_level(pool, player_id, 3)
    elif case_id == "onboarding.advance_beat":
        sd.onboarding_beat = 1
    elif case_id == "blacksmith.repair_item":
        await pool.execute(
            "UPDATE players SET data = jsonb_set(data, '{gold}', '100'::jsonb) WHERE player_id = $1",
            player_id,
        )
        await _set_skill(pool, player_id, "crafting", "trained")
        await pool.execute(
            "INSERT INTO player_inventory (player_id, item_id, data) VALUES ($1, 'shortsword_basic', $2::jsonb) "
            "ON CONFLICT (player_id, item_id) DO UPDATE SET data = $2::jsonb",
            player_id,
            json.dumps({"current_hits": 2}),
        )

    before = {"player": await _player_json(pool, player_id)}
    if case_id == "exploration.check_gather":
        before["inventory"] = await db_queries.get_player_inventory(player_id, conn=pool)
    return Scenario(sd, before)
