"""Tests for inner_fire (draethar_inner_fire.py, story-005, M3.4).

Drives the tool's _impl directly with a mock RunContext + injected mock db / queries /
hp-mutations / resonance-mutations / resonance-events / dice mods, mirroring
test_veil_ward_tools.py. Inner Fire is the Draethar active racial (spec magic.md 262-268):
once per encounter, drop Resonance by 3 and take 1d6 unpreventable self fire damage. Every
user-facing failure is a ToolError raised before any write, so an ineligible use changes nothing.

The -3 / "1d6" values come from the story-001 racial table; the real racial_resonance module is
used (the autouse seed_racial_resonance conftest fixture populates it), so the test exercises the
real lookup. dice is injected for a deterministic roll. Inner Fire is combat-scoped, so the
session carries a CombatState with the Draethar as a participant; HP is written to both the
participant (in-memory) and persisted via update_player_hp, mirroring combat_turn.py.
"""

import json
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

from draethar_inner_fire import _inner_fire_impl
from session_data import CombatParticipant, CombatState


def _player(race: str = "draethar", hp_current: int = 20) -> dict:
    return {
        "player_id": "player_1",
        "name": "Varr",
        "race": race,
        "class": "warden",
        "level": 5,
        "hp": {"current": hp_current, "max": 20},
    }


def _combat_ctx(*, resonance: int = 9, hp_current: int = 20, used: bool = False):
    ctx = make_context()
    session = ctx.userdata
    session.resonance.current = resonance
    session.draethar_inner_fire_used = used
    session.combat_state = CombatState(
        combat_id="c1",
        participants=[
            CombatParticipant(
                id="player_1", name="Varr", type="player", initiative=14, hp_current=hp_current, hp_max=20, ac=14
            ),
            CombatParticipant(id="goblin_1", name="Goblin", type="enemy", initiative=10, hp_current=7, hp_max=7, ac=13),
        ],
        initiative_order=["player_1", "goblin_1"],
    )
    return ctx


def _mocks(player: dict, *, roll_total: int = 4):
    mock_db, _conn = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=player)
    hp_mut = MagicMock()
    hp_mut.update_player_hp = AsyncMock()
    hp_mut.save_combat_state = AsyncMock()
    res_mut = MagicMock()
    res_mut.update_player_resonance = AsyncMock()
    res_events = MagicMock()
    res_events.publish_resonance_changed = AsyncMock()
    dice_mod = MagicMock()
    dice_mod.roll = MagicMock(return_value=MagicMock(total=roll_total))
    return mock_db, queries, hp_mut, res_mut, res_events, dice_mod


async def _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod):
    raw = await _inner_fire_impl(
        ctx,
        db_mod=mock_db,
        queries_mod=queries,
        hp_mutations_mod=hp_mut,
        resonance_mutations_mod=res_mut,
        resonance_events_mod=res_events,
        dice_mod=dice_mod,
    )
    return json.loads(raw)


# --- happy path: drop Resonance, take fire damage, spend the once-per-encounter use ---


async def test_inner_fire_drops_resonance_and_applies_fire_damage():
    ctx = _combat_ctx(resonance=9, hp_current=20)
    session = ctx.userdata
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(), roll_total=4)

    result = await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)

    # Resonance 9 -> 6 (-3), persisted + session synced; HUD state event pushed.
    res_mut.update_player_resonance.assert_awaited_once_with("player_1", 6, conn=ANY)
    assert session.resonance.current == 6
    res_events.publish_resonance_changed.assert_awaited_once()
    # 1d6 = 4 fire damage applied to the participant + persisted (dual HP write).
    hp_mut.update_player_hp.assert_awaited_once_with("player_1", 16, conn=ANY)
    assert session.combat_state.get_participant("player_1").hp_current == 16
    # Once-per-encounter flag spent.
    assert session.draethar_inner_fire_used is True
    # Packet shape.
    assert result["resonance_reduced"] == 3
    assert result["fire_damage"] == 4
    assert result["hp_remaining"] == 16
    assert result["state"] == "flickering"  # 6 -> flickering (E2E: overreach dropped below 9)


async def test_resonance_floors_at_zero():
    ctx = _combat_ctx(resonance=2)
    session = ctx.userdata
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(), roll_total=1)
    result = await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)
    res_mut.update_player_resonance.assert_awaited_once_with("player_1", 0, conn=ANY)
    assert session.resonance.current == 0
    assert result["resonance_reduced"] == 2  # only had 2 to give


async def test_hp_floors_at_zero():
    ctx = _combat_ctx(hp_current=3)
    session = ctx.userdata
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(hp_current=3), roll_total=6)
    result = await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)
    hp_mut.update_player_hp.assert_awaited_once_with("player_1", 0, conn=ANY)
    assert session.combat_state.get_participant("player_1").hp_current == 0
    assert result["hp_remaining"] == 0


async def test_persists_combat_state_after_self_damage():
    # combat_turn always pairs update_player_hp with save_combat_state; otherwise a mid-encounter
    # crash restores stale participant HP from combat_instances (heal-by-crash). Pin the persist
    # with the post-damage state.
    ctx = _combat_ctx(resonance=9, hp_current=20)
    session = ctx.userdata
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(), roll_total=4)

    await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)

    hp_mut.save_combat_state.assert_awaited_once_with("c1", session.combat_state.to_dict())
    # The persisted state carries the damaged participant HP (20 - 4 = 16), not the stale value.
    assert hp_mut.save_combat_state.await_args.args[1]["participants"][0]["hp_current"] == 16


# --- rejections: ToolError before any write -------------------------------------


async def test_non_draethar_rejected():
    ctx = _combat_ctx()
    session = ctx.userdata
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(race="human"))
    with pytest.raises(ToolError, match="Draethar"):
        await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)
    res_mut.update_player_resonance.assert_not_awaited()
    hp_mut.update_player_hp.assert_not_awaited()
    assert session.draethar_inner_fire_used is False


async def test_already_used_this_encounter_rejected():
    ctx = _combat_ctx(used=True)
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player())
    with pytest.raises(ToolError, match="already"):
        await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)
    res_mut.update_player_resonance.assert_not_awaited()
    hp_mut.update_player_hp.assert_not_awaited()


async def test_no_combat_rejected():
    ctx = make_context()
    ctx.userdata.resonance.current = 9
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player())
    with pytest.raises(ToolError, match="combat"):
        await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)
    queries.get_player.assert_not_awaited()  # combat gate fires before the player fetch
    res_mut.update_player_resonance.assert_not_awaited()
    hp_mut.update_player_hp.assert_not_awaited()
