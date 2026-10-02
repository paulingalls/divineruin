"""Integration coverage: combat init applies encounter-role derivation (M4.7, story-001 slice 3).

Models test_start_combat.py — mock mutations/queries/content DI, a role-tagged encounter — and
asserts the persisted CombatParticipants carry role-derived stats (not raw base stats): a Minion is
halved with its actives stripped, a Boss is doubled with a signature + one legendary action, and the
resolver modifier fields (attack_mod/dc_mod/damage_mult) are populated. Fast lane: the DB layer is
mocked, no real PG.
"""

from copy import deepcopy

import pytest
from sample_fixtures import TEST_CREATURES, make_context

from combat_init import _start_combat_impl
from creature_combat import translate_creature
from tests.combat.test_start_combat import SAMPLE_PLAYER, _make_start_combat_mocks

ROLE_ENCOUNTER = {
    "id": "role_mix",
    "name": "Role Mix",
    "difficulty": "hard",
    "recommended_party_level": 7,
    "enemies": [
        {"id": "shadeling_1", "creature_id": "hollow_shadeling", "role": "minion"},
        {"id": "warden_1", "creature_id": "hollow_warden", "role": "boss"},
    ],
}


async def _run_and_get_participants():
    mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()
    mock_content.get_encounter_template.return_value = ROLE_ENCOUNTER

    async def load(creature_id, **kwargs):
        row = deepcopy(TEST_CREATURES[creature_id])
        if creature_id == "hollow_shadeling":
            row["resistance_tags"] = ["cowardly"]
            row["actives"] = [
                {
                    "name": "Wail",
                    "description": "Test-only command.",
                    "narration_cue": "A sharp crack rings out.",
                    "audio": "test-wail",
                    "recharge": {"kind": "round", "uses": 1},
                    "kind": "command",
                    "properties": [],
                }
            ]
            base = translate_creature(row, **{**kwargs, "role": "standard"})
            assert "Wail" in [action["name"] for action in base["action_pool"]]
        return translate_creature(row, **kwargs)

    mock_content.load_creature_enemy = load
    ctx = make_context()
    await _start_combat_impl(
        ctx,
        encounter_id="role_mix",
        encounter_description="A warden and its shadelings.",
        mutations=mock_mutations,
        queries=mock_queries,
        content=mock_content,
    )
    mock_mutations.save_combat_state.assert_called_once()
    _combat_id, state_dict = mock_mutations.save_combat_state.call_args[0]
    return {p["id"]: p for p in state_dict["participants"]}


@pytest.mark.asyncio
async def test_minion_participant_is_halved_and_stripped():
    parts = await _run_and_get_participants()
    minion = parts["shadeling_1"]
    assert minion["role"] == "minion"
    assert minion["hp_max"] == 4
    assert minion["hp_current"] == 4
    assert minion["ac"] == 9
    assert {a["name"] for a in minion["action_pool"]} == {"Corrosive Touch"}
    assert minion["attack_mod"] == 0
    assert minion["dc_mod"] == -1
    assert minion["damage_mult"] == 0.75
    assert minion["legendary_actions"] == 0


@pytest.mark.asyncio
async def test_boss_participant_is_doubled_with_signature_and_legendary():
    parts = await _run_and_get_participants()
    boss = parts["warden_1"]
    assert boss["role"] == "boss"
    assert boss["hp_max"] == 110
    assert boss["ac"] == 17
    assert boss["xp_value"] == 400
    assert boss["attack_mod"] == 2
    assert boss["dc_mod"] == 2
    assert boss["damage_mult"] == 1.5
    assert boss["legendary_actions"] == 1
    assert boss["signature_ability"]["name"] == "Reality Collapse"


@pytest.mark.asyncio
async def test_player_participant_keeps_identity_role_defaults():
    parts = await _run_and_get_participants()
    player = parts[SAMPLE_PLAYER["player_id"]]
    assert player["role"] == "standard"
    assert player["attack_mod"] == 0
    assert player["damage_mult"] == 1.0
    assert player["dc_mod"] == 0


@pytest.mark.asyncio
async def test_enemy_participants_carry_category_and_loot_table_id():
    # story-002: combat_init carries the template enemy's category + loot_table_id onto the
    # participant so _end_combat_db can roll role-scaled loot/currency on victory.
    parts = await _run_and_get_participants()
    assert parts["shadeling_1"]["category"] == "hollow_drift"
    assert parts["shadeling_1"]["loot_table_id"] == "loot_hollow_drift"
    assert parts["warden_1"]["category"] == "hollow_rend"
    assert parts["warden_1"]["loot_table_id"] == "loot_hollow_warden"


@pytest.mark.asyncio
async def test_enemy_participants_carry_resistance_tags():
    # M15 story-002: combat_init carries the template enemy's Tier-3 resistance_tags onto the
    # participant so the de-escalation orchestrator shifts each enemy's disposition by its own
    # profile. An untagged enemy defaults to [] (un-de-escalatable).
    parts = await _run_and_get_participants()
    assert parts["shadeling_1"]["resistance_tags"] == ["cowardly"]
    assert parts["warden_1"]["resistance_tags"] == []


@pytest.mark.asyncio
async def test_player_participant_has_empty_loot_fields():
    # The player carries no loot table — the loot/currency overlay is enemy-only.
    player = (await _run_and_get_participants())[SAMPLE_PLAYER["player_id"]]
    assert player["category"] == ""
    assert player["loot_table_id"] == ""


@pytest.mark.asyncio
async def test_enemy_participants_carry_authored_tier():
    parts = await _run_and_get_participants()
    assert parts["shadeling_1"]["tier"] == 1
    assert parts["warden_1"]["tier"] == 2


def test_saved_participant_requires_tier_key():
    from session_data import CombatState

    row = {
        "id": "old_enemy",
        "name": "Old Enemy",
        "type": "enemy",
        "initiative": 1,
        "hp_current": 1,
        "hp_max": 1,
        "ac": 10,
        "category": "humanoid",
    }
    saved = {"combat_id": "old_combat", "participants": [row], "initiative_order": ["old_enemy"]}
    with pytest.raises(ValueError, match=r"old_enemy.*tier"):
        CombatState.from_dict(saved)


def test_saved_participant_tier_round_trips():
    from session_data import CombatParticipant, CombatState

    participant = CombatParticipant(
        id="enemy", name="Enemy", type="enemy", initiative=1, hp_current=1, hp_max=1, ac=10, tier=2
    )
    state = CombatState(combat_id="combat", participants=[participant], initiative_order=["enemy"])
    assert CombatState.from_dict(state.to_dict()).participants[0].tier == 2
