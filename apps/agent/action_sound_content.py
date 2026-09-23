import json
import logging
from pathlib import Path
from types import MappingProxyType

import event_types as E
from combat_sound_content import COMBAT_SOUND_IDS
from game_events import publish_game_event
from session_data import SessionData

logger = logging.getLogger("divineruin.action_sound_content")

_ROOT = Path(__file__).resolve().parents[2]
_CONTENT_PATH = _ROOT / "content" / "action_sounds.json"
_ASSETS = _ROOT / "apps" / "mobile" / "assets" / "sounds"


def _load_action_sounds(rows: object | None = None) -> dict[str, str]:
    if rows is None:
        rows = json.loads(_CONTENT_PATH.read_text())
    if not isinstance(rows, list) or not rows:
        raise ValueError("action sound content must be a nonempty list")
    exports: dict[str, str] = {}
    ids: set[str] = set()
    base_ids = {path.stem for path in _ASSETS.glob("*.mp3")}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("action sound rows must be objects")
        export, sound_id, asset = (row.get(field) for field in ("export", "id", "asset"))
        if (
            not isinstance(export, str)
            or not export
            or not isinstance(sound_id, str)
            or not sound_id
            or not isinstance(asset, str)
            or not asset
        ):
            raise ValueError("action sound export, id, and asset must be nonempty strings")
        if export in exports or sound_id in ids or sound_id in base_ids or sound_id in COMBAT_SOUND_IDS:
            raise ValueError(f"duplicate action sound row: {export}/{sound_id}")
        if not ((_ASSETS / f"{asset}.mp3").is_file() or (_ASSETS / "textures" / f"{asset}.mp3").is_file()):
            raise ValueError(f"unmapped action sound asset: {asset}")
        exports[export] = sound_id
        ids.add(sound_id)
    return exports


ACTION_SOUND_EXPORTS = MappingProxyType(_load_action_sounds())
ACTION_SOUND_IDS = frozenset(ACTION_SOUND_EXPORTS.values())


async def publish_action_sound(session: SessionData, sound_id: str) -> None:
    if sound_id not in ACTION_SOUND_IDS:
        raise ValueError(f"unknown action sound: {sound_id}")
    try:
        await publish_game_event(session.room, E.PLAY_SOUND, {"sound_name": sound_id}, event_bus=session.event_bus)
    except Exception:
        logger.exception("Failed to publish action sound %s", sound_id)
