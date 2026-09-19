import ast
import json
from pathlib import Path

import pytest
from sample_fixtures import make_context

import event_types as E
import tool_support
from combat_events import EventSink
from combat_support import _publish_sounds

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_DIR = REPO_ROOT / "apps" / "agent"
CONTENT_PATH = REPO_ROOT / "content" / "combat_sounds.json"
SOUNDS_DIR = REPO_ROOT / "apps" / "mobile" / "assets" / "sounds"
PRESERVED_IDS = {
    "combat_start_stinger",
    "combat_victory_stinger",
    "combat_defeat_stinger",
    "combat_fled_stinger",
    "weapon_hit",
    "weapon_miss",
    "critical_hit",
    "heartbeat_low_hp",
    "death_save_success",
    "death_save_fail",
    "death_save_critical_success",
    "player_fallen",
    "hollow_rise",
    "player_death",
    "player_stabilized",
}


def _catalog() -> list[dict[str, str]]:
    rows = json.loads(CONTENT_PATH.read_text())
    assert isinstance(rows, list)
    return rows


def test_combat_sound_catalog_preserves_wire_ids_and_bundled_assets():
    rows = _catalog()
    assert len(rows) >= 16
    exports = [row["export"] for row in rows]
    ids = [row["id"] for row in rows]
    assets = [row["asset"] for row in rows]
    assert all(isinstance(value, str) and value for value in exports + ids + assets)
    assert len(exports) == len(set(exports))
    assert len(ids) == len(set(ids))
    assert set(ids) >= PRESERVED_IDS
    for asset in assets:
        assert (SOUNDS_DIR / f"{asset}.mp3").is_file(), f"missing bundled combat sound asset: {asset}"


def test_python_exports_match_shared_combat_sound_content():
    expected = {row["export"]: row["id"] for row in _catalog()}
    actual = {name: value for name, value in vars(tool_support).items() if name.startswith("SOUND_")}
    assert actual == expected


def test_every_combat_sound_producer_is_represented_in_shared_content():
    caller_paths = []
    referenced_exports = set()
    for path in AGENT_DIR.rglob("*.py"):
        if "tests" in path.parts or ".venv" in path.parts:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        if not any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_publish_sounds"
            for node in ast.walk(tree)
        ):
            continue
        caller_paths.append(path)
        referenced_exports.update(
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id.startswith("SOUND_")
        )
    assert len(caller_paths) >= 5
    assert referenced_exports == {row["export"] for row in _catalog()}


async def test_every_shared_combat_sound_can_be_published():
    session = make_context().userdata
    sounds = [row["id"] for row in _catalog()]
    sink = EventSink()
    await _publish_sounds(session, sounds, sink=sink)
    assert [event.event_type for event in sink.captured] == [E.PLAY_SOUND] * len(sounds)
    assert [event.payload["sound_name"] for event in sink.captured] == sounds


@pytest.mark.parametrize("buffered", [False, True])
async def test_unknown_combat_sound_rejected_before_any_publication(buffered):
    session = make_context().userdata
    sink = EventSink() if buffered else None
    known = _catalog()[0]["id"]
    with pytest.raises(ValueError, match="unknown combat sound"):
        await _publish_sounds(session, [known, "unknown_combat_sound"], sink=sink)
    assert session.event_bus.drain() == []
    if sink is not None:
        assert sink.captured == []
