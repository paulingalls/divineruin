"""Pure selection of validated, authored archetype enhancements."""

from _gods_content import archetype_ids, load_gods


def synergy_for_patron(archetype_id: str, patron: dict) -> dict:
    """Select from the caller's catalog, preserving injected patron content."""
    if archetype_id not in archetype_ids():
        raise ValueError(f"Unknown archetype {archetype_id!r}.")
    matrix = patron["layer_4_synergy_matrix"]
    return matrix[archetype_id]


def get_archetype_synergy(archetype_id: str, patron_id: str) -> dict | None:
    """Return the complete row; only canonical Unbound ('none') returns None."""
    if archetype_id not in archetype_ids():
        raise ValueError(f"Unknown archetype {archetype_id!r}.")
    if patron_id == "none":
        return None
    patron = next((p for p in load_gods() if p["god_id"] == patron_id), None)
    if patron is None:
        raise ValueError(f"Unknown patron {patron_id!r}.")
    return synergy_for_patron(archetype_id, patron)


def has_engine_synergy(player: dict, implementation_id: str) -> bool:
    """Select an active implementation from the authoritative character's patron and class."""
    patron = (player.get("divine_favor") or {}).get("patron")
    if patron in (None, "none"):
        return False
    row = get_archetype_synergy(player["class"], patron)
    assert row is not None
    return any(
        clause["status"] == "active"
        and clause["resolution"] == "engine"
        and clause.get("implementation_id") == implementation_id
        for clause in row["clauses"]
    )
