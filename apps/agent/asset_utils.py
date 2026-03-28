"""Shared asset ID computation — must match server's computeAssetId."""

import hashlib
import json
import re

_VALID_SLUG_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def compute_asset_id(template_id: str, vars: dict[str, str]) -> str:
    """Replicate the server's content-addressable hash for image assets."""
    sorted_entries = sorted(vars.items())
    payload = template_id + json.dumps(sorted_entries)
    h = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"img_{h}"


def asset_url(template_id: str, vars: dict[str, str]) -> str:
    """Build a hash-based image asset URL (for dynamically generated images)."""
    aid = compute_asset_id(template_id, vars)
    return f"/api/assets/images/{aid}"


def slug_asset_url(slug: str) -> str:
    """Build a slug-based image asset URL (for pre-generated core game images)."""
    if not _VALID_SLUG_RE.match(slug):
        raise ValueError(f"Invalid asset slug: {slug!r}")
    return f"/api/assets/images/{slug}"
