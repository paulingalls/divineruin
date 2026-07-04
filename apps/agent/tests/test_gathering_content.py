"""Content-conformance for M4.6c gathering data (story-002).

Pure JSON-loading guards, no DB — mirrors test_travel_content.py. Validates two surfaces:
the ambient per-location `resource_table` (consumed by gathering.resolve_gathering) and the
fixed `gathering_nodes.json` seed (consumed by story-003's tool + M16's respawn tick).

Spec: docs/game_mechanics/game_mechanics_combat.md §Gathering During Travel (L977-1060).
"""

import json
from pathlib import Path

import gathering

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_LOCATIONS = _REPO_ROOT / "content" / "locations.json"
_MATERIALS = _REPO_ROOT / "content" / "materials_catalog.json"
_NODES = _REPO_ROOT / "content" / "gathering_nodes.json"

# Canonical fixed-node types (spec §Gathering Nodes, L1024-1040). Full content-conformance vocab.
# story-003's gathering.NODE_TYPE_SKILL is the runtime skill-routing SSOT — a *subset* (salvage_site
# routes via Investigation, not a gathering skill, so it is intentionally absent there).
_NODE_TYPES = frozenset(
    {"ore_vein", "herb_garden", "crystal_deposit", "timber_stand", "salvage_site", "hollow_residue_pool"}
)


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text())


def _locations() -> list[dict]:
    return _load(_LOCATIONS)


def _material_ids() -> set[str]:
    return {m["id"] for m in _load(_MATERIALS)}


def _location_ids() -> set[str]:
    return {loc["id"] for loc in _locations()}


# --- Ambient resource_table (mirrors gathering.RARITY_ORDER, materials catalog) ---


def test_wilderness_locations_have_a_resource_table():
    wild = [loc for loc in _locations() if loc.get("region_type") == "wilderness"]
    assert wild, "expected at least one wilderness location"
    offenders = [loc["id"] for loc in wild if "resource_table" not in loc]
    assert not offenders, f"wilderness locations missing resource_table: {offenders}"


def test_city_and_dungeon_locations_omit_resource_table():
    # Dungeons gather via fixed nodes; cities don't forage. Negative guard.
    offenders = [
        loc["id"] for loc in _locations() if loc.get("region_type") in ("city", "dungeon") and "resource_table" in loc
    ]
    assert not offenders, f"non-wilderness locations should omit resource_table: {offenders}"


def test_resource_table_keys_are_canonical_rarities():
    offenders = []
    for loc in _locations():
        table = loc.get("resource_table")
        if table is None:
            continue
        for rarity in table:
            if rarity not in gathering.RARITY_ORDER:
                offenders.append((loc["id"], rarity))
    assert not offenders, f"non-canonical rarity buckets (expect {gathering.RARITY_ORDER}): {offenders}"


def test_resource_table_materials_exist_in_catalog():
    # The bucket is regional availability, NOT a material's intrinsic catalog rarity — we only
    # check id-existence, never bucket == catalog rarity (iron_ore is catalog-common, greyvale-uncommon).
    materials = _material_ids()
    offenders = []
    for loc in _locations():
        table = loc.get("resource_table")
        if table is None:
            continue
        for ids in table.values():
            offenders.extend((loc["id"], mid) for mid in ids if mid not in materials)
    assert not offenders, f"resource_table material ids not in catalog: {offenders}"


# --- Fixed gathering_nodes seed ---


def test_every_node_targets_a_real_location():
    location_ids = _location_ids()
    offenders = [n["id"] for n in _load(_NODES) if n.get("location_id") not in location_ids]
    assert not offenders, f"gathering nodes pointing at unknown location_id: {offenders}"


def test_node_types_are_canonical():
    offenders = [(n["id"], n.get("node_type")) for n in _load(_NODES) if n.get("node_type") not in _NODE_TYPES]
    assert not offenders, f"non-canonical node_type (expect {sorted(_NODE_TYPES)}): {offenders}"


def test_node_fields_have_correct_shape():
    for n in _load(_NODES):
        assert isinstance(n["quantity"], int) and n["quantity"] > 0, f"{n['id']}: quantity must be positive int"
        assert isinstance(n["discovered"], bool), f"{n['id']}: discovered must be bool"
        assert isinstance(n["respawn_days"], int), f"{n['id']}: respawn_days must be int (cadence config)"
        assert isinstance(n["capacity"], int) and n["capacity"] > 0, f"{n['id']}: capacity must be positive int"
        assert n["capacity"] == n["quantity"], f"{n['id']}: capacity must equal seeded quantity"


def test_node_resource_types_exist_in_catalog():
    materials = _material_ids()
    offenders = [(n["id"], n.get("resource_type")) for n in _load(_NODES) if n.get("resource_type") not in materials]
    assert not offenders, f"gathering node resource_type not in catalog: {offenders}"
