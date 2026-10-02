import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sample_fixtures import SAMPLE_PLAYER, make_context, make_mock_room, published_payloads
from test_draethar_inner_fire import _combat_ctx, _invoke, _mocks, _player
from test_kaelen_gift import player

import conditions
import event_types as E
from check_resolution_attack import resolve_attack
from check_tools import _check_impl
from combat_support import apply_attack_result
from session_data import CombatState
from system_prompts import COMBAT_SYSTEM_PROMPT


@pytest.mark.parametrize("writer", ["attack", "inner_fire"])
async def test_hp_lowering_writers_trigger_gift(writer):
    ctx = _combat_ctx(hp_current=6 if writer == "inner_fire" else 10)
    ctx.userdata.party.primary.patron_id = "kaelen"
    target = ctx.userdata.combat_state.get_participant("player_1")
    if writer == "inner_fire":
        result = await _invoke(ctx, *_mocks(_player(hp_current=6), roll_total=2))
    else:
        attacker = ctx.userdata.combat_state.get_participant("goblin_1")
        action = {"name": "Claw", "damage": "1d6", "damage_type": "slashing", "properties": []}
        with (
            patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=15)),
            patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=6)),
        ):
            roll = resolve_attack({}, action, target.ac, target.hp_current)
        result = await apply_attack_result(
            ctx.userdata,
            attacker,
            action,
            target,
            roll,
            target.ac,
            mutations=MagicMock(update_player_hp=AsyncMock()),
            queries=MagicMock(get_player_inventory=AsyncMock(return_value=[])),
            concentration_break_mod=MagicMock(break_concentration_on_damage=AsyncMock(return_value=None)),
            combat_state=ctx.userdata.combat_state,
        )
    assert target.hp_current == 4
    assert target.iron_resolve_spent
    assert target.conditions[0]["type"] == "iron_resolve"
    assert result["gift_triggered"] == "Iron Resolve"


def check_context():
    ctx = make_context(party_member_ids=["player_2"])
    ctx.userdata.event_bus = MagicMock()
    rows = {pid: deepcopy(SAMPLE_PLAYER) for pid in ["player_1", "player_2"]}
    for pid, row in rows.items():
        row.update(player_id=pid, conditions=conditions.apply_condition([], "exhausted"))
    guest = player("player_2")
    guest.conditions = conditions.apply_condition(rows["player_2"]["conditions"], "iron_resolve", duration=2)
    ctx.userdata.combat_state = CombatState(
        combat_id="checks", participants=[player(), guest], initiative_order=["player_1", "player_2"]
    )
    queries = MagicMock(
        get_player=AsyncMock(side_effect=lambda pid: rows[pid]), get_player_inventory=AsyncMock(return_value=[])
    )
    queries.get_single_skill_advancement = AsyncMock(
        return_value={"tier": "untrained", "use_counter": 0, "narrative_moment_ready": False}
    )
    return ctx, rows, queries


@pytest.mark.parametrize("surface", ["save", "skill"])
async def test_check_tool_uses_only_guest_iron_resolve_for_saves(surface):
    ctx, rows, queries = check_context()
    original = deepcopy(rows)
    args: dict[str, Any] = (
        {"save_type": "wisdom", "dc": 12, "effect_on_fail": "fear"}
        if surface == "save"
        else {"skill": "athletics", "difficulty": "moderate", "context_description": "climb"}
    )
    with (
        ctx.userdata._bind_authenticated_actor("player_2", 1, lambda *_: None),
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=10)),
    ):
        boosted = json.loads(
            await _check_impl(
                ctx, surface, **args, queries=queries, skill_mutations=MagicMock(update_skill_advancement=AsyncMock())
            )
        )
        ctx.userdata.combat_state.get_participant("player_2").conditions = rows["player_2"]["conditions"]
        clean = json.loads(
            await _check_impl(
                ctx, surface, **args, queries=queries, skill_mutations=MagicMock(update_skill_advancement=AsyncMock())
            )
        )
    assert boosted["total"] - clean["total"] == (2 if surface == "save" else 0)
    assert rows == original


@pytest.mark.parametrize("combat", ["absent", "missing_guest", "no_gift"])
async def test_save_without_matching_combat_gift(combat):
    ctx, _rows, queries = check_context()
    with (
        ctx.userdata._bind_authenticated_actor("player_2", 1, lambda *_: None),
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=10)),
    ):
        boosted = json.loads(await _check_impl(ctx, "save", save_type="wisdom", dc=12, queries=queries))
        if combat == "absent":
            ctx.userdata.combat_state = None
        elif combat == "missing_guest":
            ctx.userdata.combat_state.participants.pop()
        else:
            ctx.userdata.combat_state.get_participant("player_2").conditions = []
        clean = json.loads(await _check_impl(ctx, "save", save_type="wisdom", dc=12, queries=queries))
    assert boosted["total"] - clean["total"] == 2


def test_prompt_names_packet_gift():
    assert "gift_triggered" in COMBAT_SYSTEM_PROMPT
    assert "Kaelen's surge" in COMBAT_SYSTEM_PROMPT
    assert "Iron Resolve" in COMBAT_SYSTEM_PROMPT


@pytest.mark.parametrize("damage", [1, 2])
async def test_inner_fire_surges_reach_hud_before_next_phase(damage):
    ctx = _combat_ctx(hp_current=6, room=make_mock_room())
    ctx.userdata.party.primary.patron_id = "kaelen"
    await _invoke(ctx, *_mocks(_player(hp_current=6), roll_total=damage))
    updates = [event for event in published_payloads(ctx.userdata.room) if event["type"] == E.COMBAT_UI_UPDATE]
    if damage == 1:
        assert updates == []
        return
    assert updates
    rendered = next(p for p in updates[-1]["combatants"] if p["id"] == "player_1")
    assert rendered["hpCurrent"] == 4
    assert rendered["conditions"] == [{"type": "iron_resolve", "source": "kaelen_iron_resolve", "stacks": 1}]
