"""The Architect reference roster enters through the shipped encounter."""

import json
from unittest.mock import AsyncMock

from first_blood_harness import ARCHETYPES, ARCHITECT_WORKS, architect_party
from sample_fixtures import CONTENT_ROOT

import character_spells
import db
import db_content_queries
import db_mutations
import db_queries
from architect_encounter import CREATURE_ID
from creature_catalog import query_creature_by_id
from mode_tools import enter_mode


async def test_architect_reference_party_enters(dev_db_pool, monkeypatch):
    monkeypatch.setattr(db, "_cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(db, "_cache_set", AsyncMock())
    templates = json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
    creatures = json.loads((CONTENT_ROOT / "content/creatures.json").read_text())
    template = next(row for row in templates if row["id"] == CREATURE_ID)
    creature = next(row for row in creatures if row["id"] == CREATURE_ID)
    assert await db_content_queries.get_encounter_template(CREATURE_ID) == template
    assert await query_creature_by_id(CREATURE_ID) == creature
    assert template["recommended_party_level"] == 20
    assert template["enemies"] == [{"id": "architect", "creature_id": CREATURE_ID, "role": "named"}]

    async with architect_party(dev_db_pool) as (ctx, player_ids):
        assert isinstance(await enter_mode(ctx, "combat", CREATURE_ID, "Balance reference"), tuple)
        state = ctx.userdata.combat_state
        assert state is not None
        combat_id = state.combat_id
        assert (state.location_id, state.encounter_id) == (ARCHITECT_WORKS, CREATURE_ID)
        players = {actor.id: actor for actor in state.participants if actor.type == "player"}
        assert set(players) == set(player_ids)
        assert not any(actor.type == "companion" for actor in state.participants)
        for archetype, player_id in zip(ARCHETYPES, player_ids, strict=True):
            actor = players[player_id]
            row = await db_queries.get_player(player_id)
            assert row is not None
            assert (actor.archetype_id, row["class"], actor.level, row["level"]) == (archetype, archetype, 20, 20)
            assert actor.hp_current == actor.hp_max == row["hp"]["max"]
            for name in ("hp", "stamina", "focus"):
                if name in row:
                    assert row[name]["current"] == row[name]["max"]
            assert not await character_spells.get_known(player_id)

        encounter = state.architect_encounter
        assert encounter is not None
        owner = state.get_participant(encounter["owner_id"])
        assert owner is not None
        assert (owner.creature_id, owner.role, owner.hp_max) == (CREATURE_ID, "named", creature["hp"])
        assert state.spatial is not None
        assert len(encounter["structure_ids"]) == 2
        assert set(encounter["structure_ids"]) == set(state.spatial["structures"])

    assert await db_mutations.load_combat_state(combat_id) is None
    for player_id in player_ids:
        assert await db_queries.get_player(player_id) is None
