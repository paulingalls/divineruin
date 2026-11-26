"""Dawnward Strike through registered combat tools and persisted encounters."""

from types import SimpleNamespace

import asyncpg
import pytest
from _unbound_path_fixtures import world as world
from creature_combat_helpers import participant as catalog_participant
from test_encounter_facts_damage import GOBLIN, Fight, catalog_clause, fight
from voice_condition_fixtures import participant, place_actors, spatial_record

import db
import db_mutations
from combat_participant import CombatParticipant
from creature_combat_loader import load_creature_enemy

CLAUSE = "orenthel_undead_wrath"


@pytest.fixture
async def dev_db_pool(reset_db_pool: str) -> asyncpg.Pool:
    return await db.get_pool()


async def set_target(f: Fight, species: str) -> CombatParticipant:
    enemy = await load_creature_enemy(species, encounter_id=f.combat_id, enemy_id=GOBLIN, role="standard")
    target = catalog_participant(enemy)
    target.hp_current = target.hp_max = 50
    target.ac = 14
    target.damage_affinities = {}
    target.resist_nonmagical_physical = False
    state = f.session.combat_state
    state.participants[state.participants.index(participant(state, GOBLIN))] = target
    return target


async def checkpoint(f: Fight) -> None:
    await db_mutations.save_combat_state(f.combat_id, f.session.combat_state.to_dict())
    await f.reload()


async def dawnward_strike(world: SimpleNamespace) -> None:
    async with fight(world, "orenthel", ally_hp=9) as f:
        await set_target(f, "hollow_knight")
        spatial_record(f.session.combat_state)["positions"][f.ally]["x"] = 30
        await checkpoint(f)
        await f.hit(CLAUSE)
        await catalog_clause(f, "orenthel", CLAUSE)


SCENARIOS = {CLAUSE: ("patron_synergy_combat:encounter_damage_clause", dawnward_strike, [()])}


async def test_hollow_target_bonuses_damage_with_distant_wounded_ally(world: SimpleNamespace) -> None:
    await dawnward_strike(world)


async def test_undead_category_bonuses_damage_with_wounded_companion(world: SimpleNamespace) -> None:
    async with fight(world, "orenthel", ally_hp=20) as f:
        target = await set_target(f, "bandit")
        target.category = "undead"
        assert target.hollow is None
        state = f.session.combat_state
        companion = CombatParticipant(
            id="companion_kael", name="Kael", type="companion", initiative=10, hp_current=9, hp_max=20, ac=14
        )
        state.participants.append(companion)
        state.initiative_order.append(companion.id)
        place_actors(state)
        await checkpoint(f)
        await f.hit(CLAUSE)
