"""Generated media shared by the voice processes and HTTP server."""

import os
import tempfile
from pathlib import Path


def media_dir() -> Path:
    configured = os.environ.get("MEDIA_DIR", "").strip()
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[2] / "assets/generated"


def validate_media_dir() -> None:
    production = os.environ.get("AGENT_ENV") == "production"
    if production and not os.environ.get("MEDIA_DIR", "").strip():
        raise RuntimeError("MEDIA_DIR is required in production")
    root = media_dir()
    try:
        if not production:
            root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir():
            raise OSError("root must be an existing directory")
        for directory in (root, root / "audio", root / "portraits"):
            directory.mkdir(exist_ok=True)
            with tempfile.TemporaryFile(dir=directory) as probe:
                probe.write(b"media startup probe")
                probe.flush()
    except OSError as error:
        raise RuntimeError(f"MEDIA_DIR is not writable: {root}: {error}") from error
