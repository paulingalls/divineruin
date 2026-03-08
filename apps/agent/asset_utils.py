"""Shared asset ID computation — must match server's computeAssetId."""

import hashlib
import json


def compute_asset_id(template_id: str, vars: dict[str, str]) -> str:
    """Replicate the server's content-addressable hash for image assets."""
    sorted_entries = sorted(vars.items())
    payload = template_id + json.dumps(sorted_entries)
    h = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"img_{h}"


def asset_url(template_id: str, vars: dict[str, str]) -> str:
    """Build a relative image asset URL for a given template and variables."""
    aid = compute_asset_id(template_id, vars)
    return f"/api/assets/images/{aid}"
