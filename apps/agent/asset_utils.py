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


def compute_item_image_url(item_data: dict) -> str | None:
    """Deterministic image URL for an item with an ``art_template``, or None without one.

    Lives here rather than in ``db``: it touches no connection and no cache — it is pure
    template-id + vars arithmetic — and both the inventory grant path and the combat-loot pass
    need it to build their shared ITEM_ACQUIRED payload without importing the DB layer.
    """
    art = item_data.get("art_template")
    if not art or not isinstance(art, dict):
        return None
    template_id = art.get("template_id")
    template_vars = art.get("vars", {})
    if not template_id:
        return None
    return asset_url(template_id, template_vars)
