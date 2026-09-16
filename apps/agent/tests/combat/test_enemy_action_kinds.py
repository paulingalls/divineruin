"""Enemy action kinds: an order never rolls, so no authored action can crash the attack resolver.

Bug 2a6d4b8a: content authored six non-damaging orders as damage "0" rows. The DM can declare an enemy
pool action only as an attack, and a hit then rolled dice_roll("0"), which raises. An action now has
a `kind`: absent means "attack", and a "command" resolves without a roll. Hold Person became a
save-based condition row instead (test_hold_person_paralysis.py).
"""

import ast
import json
import random
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat._helpers import _make_combat_state
from sample_fixtures import make_context

import check_resolution_attack
import combat_hold
from combat_packet import _resolve_one_packet
from combat_phase import ResolutionPacket
from declarations import Declaration, DeclarationType

_AGENT_DIR = Path(__file__).resolve().parents[2]
_CATALOG = json.loads((_AGENT_DIR.parents[1] / "content" / "encounter_templates.json").read_text())


def _content_actions() -> list[tuple[str, str, dict]]:
    return [
        (encounter["id"], enemy["id"], action)
        for encounter in _CATALOG
        for enemy in encounter["enemies"]
        for action in enemy["action_pool"]
    ]


def _content_action(enemy_id: str, name: str) -> dict:
    return next(dict(action) for _, eid, action in _content_actions() if eid == enemy_id and action["name"] == name)


def test_no_authored_attack_crashes_the_real_resolver_on_a_hit():
    zero_damage_attacks = [
        action["name"]
        for _, _, action in _content_actions()
        if str(action.get("damage")) in ("0", "")
        and not action.get("applies_condition")
        and action.get("kind", "attack") == "attack"
    ]
    assert zero_damage_attacks == []

    seed = next(s for s in range(100) if random.Random(s).randint(1, 20) > 1)
    for _, _, action in _content_actions():
        if action.get("kind", "attack") == "attack" and not action.get("applies_condition"):
            check_resolution_attack.resolve_attack(
                {"attributes": {}, "level": 1}, action, target_ac=1, target_hp=10, rng=random.Random(seed)
            )


def test_the_five_orders_are_the_command_carriers():
    carriers = sorted(
        (encounter_id, enemy_id, action["name"])
        for encounter_id, enemy_id, action in _content_actions()
        if action.get("kind") == "command"
    )
    assert carriers == [
        ("ashmark_patrol", "ashmark_sergeant", "Rally"),
        ("bandit_ambush", "bandit_captain", "Press the Attack"),
        ("cult_cell", "cult_fanatic_1", "Bless"),
        ("cult_cell", "cult_fanatic_2", "Bless"),
        ("hollow_corrupted_settlement", "hollowed_knight", "Command Lesser"),
    ]


def test_an_unknown_kind_is_refused_at_the_load_boundary():
    from encounter_actions import validate_encounter_actions

    with pytest.raises(ValueError, match="unknown kind"):
        validate_encounter_actions([{"id": "e1", "action_pool": [{"name": "Decree", "kind": "decree"}]}])


@pytest.mark.parametrize("field", ["damage", "damage_type", "applies_condition"])
def test_a_command_carrying_a_strike_field_is_refused(field):
    from encounter_actions import validate_encounter_actions

    with pytest.raises(ValueError, match=field):
        validate_encounter_actions([{"id": "e1", "action_pool": [{"name": "Rally", "kind": "command", field: "x"}]}])


def test_combat_start_runs_the_kind_check():
    tree = ast.parse((_AGENT_DIR / "combat_init.py").read_text())
    called = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "validate_encounter_actions" in called


def test_a_held_command_is_never_rolled():
    state = _make_combat_state()
    enemy = state.get_participant("goblin_scout_1")
    assert enemy is not None
    enemy.action_pool = [_content_action("ashmark_sergeant", "Rally")]
    head = {
        "actor_id": enemy.id,
        "seq": 0,
        "declaration": {"type": "attack", "action": "Rally", "target_id": "player_1"},
        "roll": None,
        "opened": [],
    }
    assert combat_hold._attack_action(state, head) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("enemy_id", "name"), [("ashmark_sergeant", "Rally"), ("cult_fanatic_1", "Bless")])
async def test_a_declared_command_resolves_without_a_roll_through_the_real_resolver(enemy_id, name):
    state = _make_combat_state()
    enemy = state.get_participant("goblin_scout_1")
    player = state.get_participant("player_1")
    assert enemy is not None and player is not None
    enemy.action_pool = [_content_action(enemy_id, name)]
    hp_before = player.hp_current
    packet = ResolutionPacket(
        actor_id=enemy.id,
        declaration=Declaration(type=DeclarationType.ATTACK, action=name, target_id=player.id),
        initiative=10,
    )

    with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=15)):
        summary = await _resolve_one_packet(
            make_context().userdata,
            state,
            packet,
            mutations=MagicMock(update_player_hp=AsyncMock()),
            queries=MagicMock(get_player_inventory=AsyncMock(return_value=[])),
            resolver=check_resolution_attack,
            concentration_break_mod=MagicMock(break_concentration_on_damage=AsyncMock(return_value=None)),
        )

    assert summary["resolved"] is True
    assert summary["kind"] == "command"
    assert "attacks" not in summary and "hit" not in summary
    assert player.hp_current == hp_before
