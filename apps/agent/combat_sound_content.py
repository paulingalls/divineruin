import json
from pathlib import Path
from types import MappingProxyType

_CONTENT_PATH = Path(__file__).resolve().parents[2] / "content" / "combat_sounds.json"


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
    return exports


COMBAT_SOUND_EXPORTS = MappingProxyType(_load_combat_sounds())
COMBAT_SOUND_IDS = frozenset(COMBAT_SOUND_EXPORTS.values())
