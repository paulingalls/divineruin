import json
from pathlib import Path

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
}


def test_catalog_and_python_exports_match_fixed_rows():
    rows = json.loads(CONTENT.read_text())
    assert len(rows) == len(ROWS) == 17
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


async def test_unknown_id_rejected_before_publication():
    session = make_context().userdata
    with pytest.raises(ValueError, match="unknown action sound"):
        await publish_action_sound(session, "unknown_action_sound")
    assert session.event_bus.drain() == []
