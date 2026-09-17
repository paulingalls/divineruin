import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from combat._helpers import _resolve_deps, _resolve_round
from sample_fixtures import make_context

import conditions
from combat_init import _start_combat_impl
from tests.combat.test_start_combat import SAMPLE_PLAYER, _make_start_combat_mocks


def _ashmark_patrol():
    path = Path(__file__).resolve().parents[4] / "content" / "encounter_templates.json"
    return next(row for row in json.loads(path.read_text()) if row["id"] == "ashmark_patrol")


async def _started_patrol(player=None):
    mutations, queries, content = _make_start_combat_mocks()
    content.get_encounter_template.return_value = _ashmark_patrol()
    content.get_faction = AsyncMock(
        return_value={
            "id": "thornwatch",
            "name": "The Thornwatch",
            "reputation_tiers": {"neutral": {"threshold": 0}, "friendly": {"threshold": 5}},
        }
    )
    queries.get_player_faction_reputation = AsyncMock(return_value=0)
    queries.get_player.return_value = player or SAMPLE_PLAYER
    ctx = make_context()
    await _start_combat_impl(
        ctx,
        "ashmark_patrol",
        "The patrol closes in.",
        mutations=mutations,
        queries=queries,
        content=content,
    )
    return ctx


def test_all_four_shield_bashes_are_save_only_prone_and_longswords_are_unchanged():
    soldiers = [enemy for enemy in _ashmark_patrol()["enemies"] if enemy["id"].startswith("ashmark_soldier_")]
    assert len(soldiers) == 4
    for soldier in soldiers:
        actions = {action["name"]: action for action in soldier["action_pool"]}
        assert actions["Longsword"]["damage"] == "1d8+2"
        bash = actions["Shield Bash"]
        assert {
            key: bash[key] for key in ("damage", "damage_type", "properties", "applies_condition", "save", "dc")
        } == {
            "damage": "0",
            "damage_type": "none",
            "properties": [],
            "applies_condition": "prone",
            "save": "strength",
            "dc": 12,
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(("roll", "outcome"), [(1, "condition_inflicted"), (20, "condition_resisted")])
async def test_started_shield_bash_resolves_as_a_save_without_attack_or_damage(roll, outcome):
    ctx = await _started_patrol()
    state = ctx.userdata.combat_state
    player = state.get_participant("player_1")
    soldier = state.get_participant("ashmark_soldier_1")
    bash = next(action for action in soldier.action_pool if action["name"] == "Shield Bash")
    assert bash["applies_condition"] == "prone"
    starting_hp = player.hp_current
    state.beat = "resolution"
    state.pending_declarations = {
        player.id: {"type": "defend"},
        soldier.id: {"type": "attack", "action": "Shield Bash", "target_id": player.id},
    }

    deps = _resolve_deps()
    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=roll)),
        patch("reaction_windows.post_roll_triggers") as post_roll_triggers,
    ):
        result = await _resolve_round(ctx, **deps)

    packet = next(row for row in result["packets"] if row["actor_id"] == soldier.id)
    assert packet[outcome] == "prone"
    assert "hit" not in packet and "damage" not in packet
    assert player.hp_current == starting_hp
    deps["resolver"].resolve_attack.assert_not_called()
    deps["mutations"].update_player_hp.assert_not_awaited()
    post_roll_triggers.assert_not_called()
    assert conditions.has_condition(ctx.userdata.combat_state.get_participant(player.id).conditions, "prone") is (
        outcome == "condition_inflicted"
    )
