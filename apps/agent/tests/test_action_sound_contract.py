import ast
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sample_fixtures import make_context

from action_sound_content import ACTION_SOUND_EXPORTS, ACTION_SOUND_IDS, _load_action_sounds, publish_action_sound

ROOT = Path(__file__).resolve().parents[3]
CONTENT = ROOT / "content" / "action_sounds.json"
ASSETS = ROOT / "apps" / "mobile" / "assets" / "sounds"
ROWS = {
    ("ACTION_TRAVEL", "action_travel", "footstep_stone"),
    ("ACTION_MOVE", "action_move", "footstep_stone"),
    ("ACTION_VEIL_WARD_RAISE", "action_veil_ward_raise", "spell_arcane_force"),
    ("ACTION_VEIL_WARD_DISMISS", "action_veil_ward_dismiss", "spell_arcane_force"),
    ("ACTION_VEIL_ANCHOR", "action_veil_anchor", "spell_arcane_force"),
    ("ACTION_ABILITY", "action_ability", "spell_cast"),
    ("ACTION_GATHER", "action_gather", "item_pickup"),
    ("ACTION_BEGIN_TRAINING", "action_begin_training", "sword_clash"),
    ("ACTION_BEGIN_CRAFTING", "action_begin_crafting", "shield_block"),
    ("ACTION_BEGIN_COMPANION_ERRAND", "action_begin_companion_errand", "footstep_stone"),
    ("ACTION_BEGIN_EXPERIMENT", "action_begin_experiment", "spell_arcane_force"),
    ("ACTION_BEGIN_WORKSPACE", "action_begin_workspace", "notification"),
    ("ACTION_RESOLVE_COMPANION_ERRAND", "action_resolve_companion_errand", "notification"),
    ("ACTION_RESOLVE_TRAINING_MIDPOINT", "action_resolve_training_midpoint", "notification"),
    ("ACTION_LEARN_RECIPE", "action_learn_recipe", "discovery_chime"),
    ("ACTION_LEARN_SPELL", "action_learn_spell", "discovery_chime"),
    ("ACTION_REPAIR_ITEM", "action_repair_item", "shield_block"),
    ("ACTION_ENTER_MODE_BLACKSMITH", "action_enter_mode_blacksmith", "shield_block"),
    ("ACTION_ENTER_MODE_DISPATCH", "action_enter_mode_dispatch", "notification"),
    ("ACTION_ADVANCE_ONBOARDING_BEAT", "action_advance_onboarding_beat", "quest_sting"),
    ("ACTION_FINALIZE_CHARACTER", "action_finalize_character", "level_up_sting"),
}


def test_catalog_and_python_exports_match_fixed_rows():
    rows = json.loads(CONTENT.read_text())
    assert len(rows) == len(ROWS) == 21
    assert {(row["export"], row["id"], row["asset"]) for row in rows} == ROWS
    assert dict(ACTION_SOUND_EXPORTS) == {export: sound_id for export, sound_id, _ in ROWS}
    assert {sound_id for _, sound_id, _ in ROWS} == ACTION_SOUND_IDS
    for _, _, asset in ROWS:
        assert (ASSETS / f"{asset}.mp3").is_file() or (ASSETS / "textures" / f"{asset}.mp3").is_file()


@pytest.mark.parametrize(
    "bad_rows",
    [
        lambda rows: [*rows, rows[0]],
        lambda rows: [*rows, {"export": "COLLISION", "id": "dice_roll", "asset": "spell_cast"}],
        lambda rows: [*rows, {"export": "COLLISION", "id": "weapon_hit", "asset": "spell_cast"}],
        lambda rows: [{**rows[0], "asset": "missing_action_asset"}, *rows[1:]],
        lambda rows: [],
    ],
)
def test_bad_catalog_rejected_by_real_loader(bad_rows):
    rows = json.loads(CONTENT.read_text())
    with pytest.raises(ValueError):
        _load_action_sounds(bad_rows(rows))


async def test_known_id_publish_failure_is_logged_and_returns(caplog):
    session = make_context().userdata
    error = RuntimeError("cue transport failed")
    with patch("action_sound_content.publish_game_event", new_callable=AsyncMock, side_effect=error) as publish:
        with caplog.at_level(logging.ERROR):
            await publish_action_sound(session, ACTION_SOUND_EXPORTS["ACTION_TRAVEL"])
    publish.assert_awaited_once()
    call = publish.await_args
    assert call is not None
    assert call.args[0] is session.room
    assert call.kwargs["event_bus"] is session.event_bus
    records = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(records) == 1
    assert records[0].exc_info is not None
    assert records[0].exc_info[1] is error


async def test_unknown_id_rejected_before_publication():
    session = make_context().userdata
    with patch("action_sound_content.publish_game_event", new_callable=AsyncMock) as publish:
        with pytest.raises(ValueError, match="unknown action sound"):
            await publish_action_sound(session, "unknown_action_sound")
    publish.assert_not_awaited()
    assert session.event_bus.drain() == []


def test_no_action_sound_call_has_local_exception_handler():
    agent_dir = ROOT / "apps" / "agent"
    assert agent_dir.is_dir()
    modules = sorted(agent_dir.glob("*.py"))
    assert modules
    call_count = 0
    violations = []
    for module in modules:
        tree = ast.parse(module.read_text(), filename=str(module))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else None
            )
            if name != "publish_action_sound":
                continue
            call_count += 1
            ancestor = parents.get(node)
            while ancestor is not None:
                if isinstance(ancestor, (ast.Try, ast.TryStar)):
                    for handler in ancestor.handlers:
                        caught = handler.type
                        types = caught.elts if isinstance(caught, ast.Tuple) else [caught]
                        if caught is None or any(isinstance(t, ast.Name) and t.id == "Exception" for t in types):
                            violations.append(f"{module}:{node.lineno}")
                ancestor = parents.get(ancestor)
    assert call_count > 0
    assert not violations, violations
