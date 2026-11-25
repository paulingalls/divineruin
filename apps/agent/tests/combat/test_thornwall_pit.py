import combat_melee_approach
from combat_participant import CombatParticipant
from combat_spatial import require_spatial
from combat_state import CombatState
from combat_structures import THORNWALL, add_wall

CLAW = {"name": "Claw", "type": "melee", "damage": "1d6", "kind": "attack"}


def field(enemy_x: float, player_x: float, speed: int):
    enemy = CombatParticipant("brute", "Brute", "enemy", 10, 30, 30, 12)
    player = CombatParticipant("rook", "Rook", "player", 10, 30, 30, 12)
    state = CombatState("c", [enemy, player], ["brute", "rook"])
    state.spatial = {
        "positions": {"brute": {"x": enemy_x, "y": 0.0, "z": 0.0}, "rook": {"x": player_x, "y": 0.0, "z": 0.0}},
        "locations": {},
        "zones": {},
        "speeds": {"brute": speed, "rook": 30},
        "structures": {},
    }
    return state, enemy, player


async def test_enemy_short_of_thornwall_cannot_strike_across_it():
    state, enemy, player = field(14.0, 8.0, 3)
    add_wall(state, "thorns", "Thornwall", {"x": 10, "y": -10, "z": 0}, {"x": 10, "y": 10, "z": 0}, kind=THORNWALL)

    facts = await combat_melee_approach.prepare(None, state, enemy, player, CLAW, {})
    assert facts is not None

    assert require_spatial(state)["positions"]["brute"]["x"] == 11.0
    assert facts["attack_resolved"] is False and facts["reason"] == "Line blocked by Thornwall (thorns)"
    assert "thornwall_id" not in facts


async def test_pitted_enemy_climbs_out_instead_of_reaching_thornwall():
    state, enemy, player = field(25.0, 0.0, 30)
    state.architect_encounter = {
        "owner_id": "architect",
        "structure_ids": [],
        "construct_ids": [],
        "phase": "active",
        "reshape_round": 0,
        "reaction_round": 0,
        "reshape_count": 0,
        "floors": {"f": {"min": {"x": 15, "y": -10, "z": 0}, "max": {"x": 30, "y": 10, "z": 0}}},
        "pits": {"brute": "f"},
    }
    add_wall(state, "thorns", "Thornwall", {"x": 10, "y": -10, "z": 0}, {"x": 10, "y": 10, "z": 0}, kind=THORNWALL)

    facts = await combat_melee_approach.prepare(None, state, enemy, player, CLAW, {})
    assert facts is not None

    assert facts["left_pit"] is True
    assert "thornwall_id" not in facts
    assert require_spatial(state)["positions"]["brute"]["x"] == 25.0
    assert "brute" not in state.architect_encounter["pits"]
