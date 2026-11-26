"""Pure selection of validated, authored archetype enhancements."""

from typing import Literal, TypedDict

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
    return has_engine_clause(row, implementation_id)


def has_engine_clause(synergy: dict, implementation_id: str) -> bool:
    return _engine_clause(synergy, implementation_id) is not None


def _engine_clause(synergy: dict, implementation_id: str) -> dict | None:
    return next(
        (
            clause
            for clause in synergy["clauses"]
            if clause["status"] == "active"
            and clause["resolution"] == "engine"
            and clause.get("implementation_id") == implementation_id
        ),
        None,
    )


class ContextSynergyReceipt(TypedDict):
    tag: str
    applied: bool
    bonus: int
    clause_id: str | None
    clause_name: str | None
    effect: str | None
    reason: Literal["applied", "unheld", "skill_mismatch"]


CONTEXT_TAGS = frozenset(
    clause["synergy_context"]
    for god in load_gods()
    for row in god["layer_4_synergy_matrix"].values()
    for clause in row["clauses"]
    if clause.get("kind") == "context_check"
) | {"none"}


def validate_synergy_context(tag: str) -> str:
    if not isinstance(tag, str) or tag not in CONTEXT_TAGS:
        raise ValueError(f"Unknown synergy_context: {tag!r}")
    return tag


def context_skill_bonus(player: dict, skill: str, tag: str) -> ContextSynergyReceipt | None:
    if tag == "none":
        return None
    patron = (player.get("divine_favor") or {}).get("patron")
    row = get_archetype_synergy(player["class"], "none" if patron is None else patron)
    if row is not None:
        for clause in row["clauses"]:
            if (
                clause.get("synergy_context") == tag
                and clause["status"] == "active"
                and clause["resolution"] == "engine"
            ):
                applies = clause["skill"] is None or clause["skill"] == skill
                return ContextSynergyReceipt(
                    tag=tag,
                    applied=applies,
                    bonus=int(clause["bonus"]) if applies else 0,
                    clause_id=clause["implementation_id"],
                    clause_name=row["name"],
                    effect=clause["effect"],
                    reason="applied" if applies else "skill_mismatch",
                )
    return ContextSynergyReceipt(
        tag=tag, applied=False, bonus=0, clause_id=None, clause_name=None, effect=None, reason="unheld"
    )


def discovery_skill_bonus(player: dict, skill: str) -> ContextSynergyReceipt | None:
    if skill != "investigation":
        return None
    patron = (player.get("divine_favor") or {}).get("patron")
    if patron is None:
        return None
    row = get_archetype_synergy(player["class"], patron)
    if row is None:
        return None
    clause = _engine_clause(row, "veythar_hidden_knowledge")
    if clause is None:
        return None
    return ContextSynergyReceipt(
        tag="hidden_information",
        applied=True,
        bonus=1,
        clause_id=clause["implementation_id"],
        clause_name=row["name"],
        effect=clause["effect"],
        reason="applied",
    )
