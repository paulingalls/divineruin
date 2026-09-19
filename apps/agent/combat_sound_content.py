import json
from pathlib import Path
from types import MappingProxyType

_CONTENT_PATH = Path(__file__).resolve().parents[2] / "content" / "combat_sounds.json"
_REQUIRED_EXPORTS = {
    "SOUND_COMBAT_START",
    "SOUND_COMBAT_VICTORY",
    "SOUND_COMBAT_DEFEAT",
    "SOUND_COMBAT_FLED",
    "SOUND_ATTACK_HIT",
    "SOUND_ATTACK_MISS",
    "SOUND_ATTACK_CRITICAL",
    "SOUND_HEARTBEAT",
    "SOUND_DEATH_SAVE_SUCCESS",
    "SOUND_DEATH_SAVE_FAIL",
    "SOUND_DEATH_SAVE_CRITICAL",
    "SOUND_PLAYER_FALLEN",
    "SOUND_HOLLOW_RISE",
    "SOUND_PLAYER_DEATH",
    "SOUND_PLAYER_STABILIZED",
    "SOUND_SAVE_DAMAGE",
}


def _load_combat_sounds() -> dict[str, str]:
    rows = json.loads(_CONTENT_PATH.read_text())
    if not isinstance(rows, list) or not rows:
        raise ValueError("combat sound content must be a nonempty list")
    exports: dict[str, str] = {}
    ids = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("combat sound rows must be objects")
        export, sound_id, asset = (row.get(field) for field in ("export", "id", "asset"))
        if (
            not isinstance(export, str)
            or not export
            or not isinstance(sound_id, str)
            or not sound_id
            or not isinstance(asset, str)
            or not asset
        ):
            raise ValueError("combat sound export, id, and asset must be nonempty strings")
        if export in exports or sound_id in ids:
            raise ValueError(f"duplicate combat sound row: {export}/{sound_id}")
        exports[export] = sound_id
        ids.add(sound_id)
    if set(exports) != _REQUIRED_EXPORTS:
        raise ValueError(f"combat sound exports do not match required exports: {sorted(exports)}")
    return exports


COMBAT_SOUND_EXPORTS = MappingProxyType(_load_combat_sounds())
COMBAT_SOUND_IDS = frozenset(COMBAT_SOUND_EXPORTS.values())
