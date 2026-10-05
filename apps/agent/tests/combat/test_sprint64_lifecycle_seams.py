import json
from dataclasses import asdict
from pathlib import Path

import pytest
from _hollow_resonance_fixtures import hollow, scenario
from combat.test_choir_encounter import start_choir
from sample_fixtures import make_db_mod

import choir_scene
import combat_spatial
from combat_action_availability import available_actions
from combat_spatial_entry import build_spatial
from combat_state import CombatState


@pytest.mark.asyncio
async def test_reentry_discards_old_silence_exposure_without_extending_suppression(mock_combat_agent_factory):
    ctx, _, mutations, queries = await start_choir()
    state = ctx.userdata.combat_state
    source = state.get_participant("choir_zone")
    assert source is not None
    source.choir_silence_exposed = True
    source.choir_suppression = {"active": False, "expires_round": 3}
    retained = {
        "source_id": choir_scene.key(state.location_id),
        "location_id": state.location_id,
        "status": "dormant",
        "owner": asdict(source),
        "phase": "search",
        "round": 4,
    }
    queries.get_player.return_value = {"flags": {choir_scene.key(state.location_id): json.dumps(retained)}}
    await choir_scene.start(
        ctx.userdata, state, retained, mutations=mutations, queries=queries, db_mod=make_db_mod()[0]
    )
    restored = state.get_participant("choir_zone")
    assert restored is not None
    assert not restored.choir_silence_exposed
    assert restored.choir_suppression == {"active": False, "expires_round": 3}
    assert available_actions(restored)


def test_dead_authored_hollow_aura_is_absent_after_persisted_reload():
    _, state, _ = scenario(distance=5)
    encounter = next(
        row
        for row in json.loads((Path(__file__).resolve().parents[4] / "content/encounter_templates.json").read_text())
        if row["id"] == "ruins_mawling_pair"
    )
    source, other = hollow("mawling_1"), hollow("mawling_2")
    state.participants = [state.participants[0], source, other]
    state.initiative_order = [actor.id for actor in state.participants]
    state.spatial = build_spatial(
        encounter, [("player_1", {"speed": 30})], [{"id": actor.id, "speed": 30} for actor in (source, other)]
    )
    state.spatial["positions"]["player_1"] = dict(state.spatial["positions"][source.id])
    zone_id = f"{source.id}_corruption_aura"
    assert "player_1" in combat_spatial.facts(state, "player_1")["zones"][zone_id]["members"]
    source.is_dead = True
    source.hp_current = 0
    reloaded = CombatState.from_dict(state.to_dict())
    facts = combat_spatial.facts(reloaded, "player_1")
    assert zone_id not in facts["zones"]
    assert other.id in facts["positions"]
