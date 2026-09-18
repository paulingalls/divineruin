import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from combat._helpers import _make_combat_state
from sample_fixtures import make_context

import combat_prompts
import conditions
from check_resolution_save import roll_participant_save
from combat_enemy_action import _resolve_enemy_condition_packet
from combat_init import _start_combat_impl
from combat_maneuver import resolve_maneuver
from declarations import Declaration, DeclarationType
from session_data import CombatState
from tests.combat.test_start_combat import SAMPLE_PLAYER, _make_start_combat_mocks

ROOT = Path(__file__).parents[4]


def _content_row(path, row_id):
    rows = json.loads((ROOT / path).read_text())
    return next(row for row in rows if row["id"] == row_id)


async def _started_with(item_id, encounter_id="hollow_patrol_greyvale"):
    item = _content_row("content/items.json", item_id)
    encounter = _content_row("content/encounter_templates.json", encounter_id)
    mutations, queries, content = _make_start_combat_mocks()
    queries.get_player_inventory.return_value = [item]
    content.get_encounter_template.return_value = encounter
    ctx = make_context()
    await _start_combat_impl(
        ctx,
        encounter_id=encounter_id,
        encounter_description="The protection is tested.",
        mutations=mutations,
        queries=queries,
        content=content,
    )
    state = ctx.userdata.combat_state
    assert state is not None
    queries.get_player_inventory.assert_awaited_once_with("player_1")
    return ctx, state


def _participant(state, participant_id):
    participant = state.get_participant(participant_id)
    assert participant is not None
    return participant


@pytest.mark.asyncio
async def test_combat_init_folds_carried_item_traits_and_round_trips():
    _ctx, state = await _started_with("stillheart")
    bearer = _participant(state, "player_1")

    assert bearer.condition_immunities == {"charmed": "Stillheart"}
    assert bearer.save_advantages == {"wisdom": "Stillheart"}
    assert bearer.advantage_vs == {}
    rebuilt = CombatState.from_dict(state.to_dict())
    assert _participant(rebuilt, "player_1").save_advantages == {"wisdom": "Stillheart"}


@pytest.mark.asyncio
async def test_combat_init_reads_and_keeps_each_party_members_own_inventory():
    stillheart = _content_row("content/items.json", "stillheart")
    cloak = _content_row("content/items.json", "cloak_steppe_winds")
    encounter = _content_row("content/encounter_templates.json", "hollow_patrol_greyvale")
    mutations, queries, content = _make_start_combat_mocks()
    second = deepcopy(SAMPLE_PLAYER)
    second.update(player_id="player_2", name="Bren")
    queries.get_players_for_update = AsyncMock(return_value={"player_2": second})
    queries.get_player_inventory = AsyncMock(
        side_effect=lambda player_id: [stillheart] if player_id == "player_1" else [cloak]
    )
    content.get_encounter_template.return_value = encounter
    ctx = make_context(party_member_ids=["player_2"])

    await _start_combat_impl(
        ctx,
        encounter_id="hollow_patrol_greyvale",
        encounter_description="The party is tested.",
        mutations=mutations,
        queries=queries,
        content=content,
    )

    state = ctx.userdata.combat_state
    assert state is not None
    assert _participant(state, "player_1").save_advantages == {"wisdom": "Stillheart"}
    assert _participant(state, "player_2").advantage_vs == {
        "prone": "Cloak of the Steppe Winds",
        "push": "Cloak of the Steppe Winds",
    }
    assert queries.get_player_inventory.await_args_list == [call("player_1"), call("player_2")]


@pytest.mark.asyncio
async def test_real_hollow_shriek_cannot_frighten_choirs_silence_bearer():
    ctx, state = await _started_with("choirs_silence", "hollow_patrol_greyvale")
    attacker = _participant(state, "hollow_rend_1")
    target = _participant(state, "player_1")
    action = next(action for action in attacker.action_pool if action["name"] == "Hollow Shriek")
    decl = Declaration(type=DeclarationType.ATTACK, action=action["name"], target_id=target.id)

    with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=2)):
        summary = await _resolve_enemy_condition_packet(
            ctx.userdata,
            attacker,
            decl,
            action,
            state=state,
            conn=object(),
        )

    assert not conditions.has_condition(target.conditions, "frightened")
    assert summary["condition_immune"] == "frightened"
    assert summary["condition_immunity_source"] == "Choir's Silence"


@pytest.mark.asyncio
async def test_real_hollow_shriek_uses_stillheart_wisdom_advantage_and_names_source():
    ctx, state = await _started_with("stillheart", "hollow_patrol_greyvale")
    attacker = _participant(state, "hollow_rend_1")
    target = _participant(state, "player_1")
    action = next(action for action in attacker.action_pool if action["name"] == "Hollow Shriek")
    decl = Declaration(type=DeclarationType.ATTACK, action=action["name"], target_id=target.id)

    with patch(
        "check_resolution.dice_roll",
        side_effect=[SimpleNamespace(total=3), SimpleNamespace(total=18)],
    ) as dice_roll:
        summary = await _resolve_enemy_condition_packet(
            ctx.userdata,
            attacker,
            decl,
            action,
            state=state,
            conn=object(),
        )

    assert dice_roll.call_count == 2
    assert summary["condition_resisted"] == "frightened"
    assert summary["save_advantage_source"] == "Stillheart"
    assert "save_advantage" not in summary


@pytest.mark.asyncio
async def test_carried_item_condition_immunity_blocks_landing_and_names_source():
    state = _make_combat_state()
    target = _participant(state, "player_1")
    target.condition_immunities = {"charmed": "Stillheart"}
    attacker = _participant(state, "goblin_scout_1")
    action = {"name": "Beguiling Call", "applies_condition": "charmed", "save": "charisma", "dc": 12}
    decl = Declaration(
        type=DeclarationType.ABILITY,
        action="Beguiling Call",
        target_id=target.id,
    )
    rng = MagicMock()
    rng.randint.return_value = 2

    summary = await _resolve_enemy_condition_packet(
        make_context().userdata,
        attacker,
        decl,
        action,
        state=state,
        conn=object(),
        save_resolver=MagicMock(
            roll_participant_save=MagicMock(
                return_value=roll_participant_save(target, "charisma", 12, "charmed", rng=rng)
            )
        ),
    )

    assert not conditions.has_condition(target.conditions, "charmed")
    assert summary["condition_immune"] == "charmed"
    assert summary["condition_immunity_source"] == "Stillheart"


def test_save_advantage_is_applied_at_participant_save_ssot():
    state = _make_combat_state()
    bearer = _participant(state, "player_1")
    bearer.save_advantages = {"wisdom": "Stillheart"}
    rng = MagicMock()
    rng.randint.side_effect = [3, 18]

    result = roll_participant_save(bearer, "WIS", 12, "frightened", rng=rng)

    assert rng.randint.call_count == 2
    assert result.roll == 18
    assert result.advantage_applied is True


def test_non_bearer_save_draws_one_die():
    state = _make_combat_state()
    rng = MagicMock()
    rng.randint.return_value = 18

    result = roll_participant_save(_participant(state, "player_1"), "wisdom", 12, "frightened", rng=rng)

    assert rng.randint.call_count == 1
    assert result.roll == 18
    assert result.advantage_applied is False


@pytest.mark.parametrize("token", ["prone", "push"])
def test_item_opposition_advantage_drives_shove_defence(token):
    state = _make_combat_state()
    attacker = _participant(state, "goblin_scout_1")
    target = _participant(state, "player_1")
    target.advantage_vs = {token: "Cloak of the Steppe Winds"}
    attacker.attributes = {"strength": 14, "dexterity": 10}
    target.attributes = {"strength": 10, "dexterity": 10}
    decl = Declaration(type=DeclarationType.MANEUVER, target_id=target.id)
    rng = MagicMock()
    rng.randint.side_effect = [12, 3, 18]

    summary = resolve_maneuver(state, attacker, decl, rng=rng)

    assert rng.randint.call_count == 3
    assert summary["shove"] == "resisted"
    assert summary["advantage_vs"] == "Cloak of the Steppe Winds"


def test_a_won_shove_blocked_by_a_carried_item_names_that_item():
    # _land_condition_on_one now refuses prone for a carried immunity too, so the maneuver's
    # blocked-shove branch can no longer assume the skill capability is what stopped it.
    state = _make_combat_state()
    attacker = _participant(state, "goblin_scout_1")
    target = _participant(state, "player_1")
    target.condition_immunities = {"prone": "Stillheart"}
    attacker.attributes = {"strength": 20, "dexterity": 10}
    target.attributes = {"strength": 1, "dexterity": 1}
    decl = Declaration(type=DeclarationType.MANEUVER, target_id=target.id)
    rng = MagicMock()
    rng.randint.side_effect = [20, 1]

    summary = resolve_maneuver(state, attacker, decl, rng=rng)

    assert summary["shove"] == "resisted"
    assert summary["condition_immunity_source"] == "Stillheart"
    assert "prone_immunity" not in summary  # no null attribution to the skill capability


def test_item_protection_packet_vocabulary_reaches_dm():
    assert all(
        key in combat_prompts.COMBAT_PROMPT
        for key in ("condition_immunity_source", "save_advantage_source", "advantage_vs")
    )
