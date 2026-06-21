"""Integration coverage: combat init applies encounter-role derivation (M4.7, story-001 slice 3).

Models test_start_combat.py — mock mutations/queries/content DI, a role-tagged encounter — and
asserts the persisted CombatParticipants carry role-derived stats (not raw base stats): a Minion is
halved with its actives stripped, a Boss is doubled with a signature + one legendary action, and the
resolver modifier fields (attack_mod/dc_mod/damage_mult) are populated. Fast lane: the DB layer is
mocked, no real PG.
"""

import pytest
from sample_fixtures import make_context

from combat_init import _start_combat_impl
from tests.combat.test_start_combat import SAMPLE_PLAYER, _make_start_combat_mocks

# A mixed-role encounter: one Minion (a basic attack + an active ability to strip) and one Boss
# (an authored signature ability + a legendary scaffold).
ROLE_ENCOUNTER = {
    "id": "role_mix",
    "name": "Role Mix",
    "difficulty": "hard",
    "enemies": [
        {
            "id": "shadeling_1",
            "name": "Shadeling",
            "role": "minion",
            "category": "hollow_drift",
            "loot_table_id": "loot_hollow_drift",
            "level": 2,
            "ac": 13,
            "hp": 16,
            "attributes": {"strength": 8, "dexterity": 12, "constitution": 10},
            "action_pool": [
                {"name": "Claw", "damage": "1d6", "damage_type": "slashing", "properties": []},
                {"name": "Wail", "damage": "0", "damage_type": "none", "properties": ["debuff"]},
            ],
            "xp_value": 50,
        },
        {
            "id": "warden_1",
            "name": "Hollow Warden",
            "role": "boss",
            "category": "hollow_rend",
            "loot_table_id": "loot_hollow_warden",
            "level": 4,
            "ac": 14,
            "hp": 20,
            "attributes": {"strength": 16, "dexterity": 10, "constitution": 16},
            "action_pool": [
                {"name": "Void Lash", "damage": "2d6", "damage_type": "necrotic", "properties": []},
            ],
            "xp_value": 200,
            "signature_ability": {"name": "Corruption Pulse", "description": "AoE necrotic burst."},
        },
    ],
}


async def _run_and_get_participants():
    mock_mutations, mock_queries, mock_content = _make_start_combat_mocks()
    mock_content.get_encounter_template.return_value = ROLE_ENCOUNTER
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
    assert minion["hp_max"] == 8  # 16 * 0.5
    assert minion["hp_current"] == 8
    assert minion["ac"] == 12  # 13 - 1
    assert {a["name"] for a in minion["action_pool"]} == {"Claw"}  # Wail (active) stripped
    assert minion["attack_mod"] == 0
    assert minion["dc_mod"] == -1
    assert minion["damage_mult"] == 0.75
    assert minion["legendary_actions"] == 0


@pytest.mark.asyncio
async def test_boss_participant_is_doubled_with_signature_and_legendary():
    parts = await _run_and_get_participants()
    boss = parts["warden_1"]
    assert boss["role"] == "boss"
    assert boss["hp_max"] == 40  # 20 * 2.0
    assert boss["ac"] == 16  # 14 + 2
    assert boss["xp_value"] == 400  # 200 * 2.0
    assert boss["attack_mod"] == 2
    assert boss["dc_mod"] == 2
    assert boss["damage_mult"] == 1.5
    assert boss["legendary_actions"] == 1
    assert boss["signature_ability"]["name"] == "Corruption Pulse"


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
async def test_player_participant_has_empty_loot_fields():
    # The player carries no loot table — the loot/currency overlay is enemy-only.
    player = (await _run_and_get_participants())[SAMPLE_PLAYER["player_id"]]
    assert player["category"] == ""
    assert player["loot_table_id"] == ""
