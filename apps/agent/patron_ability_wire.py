"""Validation of server-authored patron HUD snapshots."""


def validate_snapshot(payload: dict) -> None:
    if not isinstance(payload.get("player_id"), str) or not payload["player_id"].strip():
        raise ValueError("Patron snapshot requires player_id")
    revision = payload.get("patron_revision")
    if type(revision) is not int or not 0 <= revision <= 2**53 - 1:
        raise ValueError("Patron snapshot requires a safe nonnegative revision")
    favor = payload.get("divine_favor")
    if "divine_favor" in payload and favor is None and payload.get("abilities") == []:
        return
    if not isinstance(favor, dict) or not isinstance(favor.get("patron"), str) or not favor["patron"].strip():
        raise ValueError("Malformed patron favor")
    if any(type(favor.get(k)) is not int for k in ("level", "max")):
        raise ValueError("Patron favor requires integers")
    if not 0 <= favor["level"] <= favor["max"] or favor["max"] <= 0:
        raise ValueError("Patron favor outside range")
    rows = payload.get("abilities")
    if not isinstance(rows, list):
        raise ValueError("Patron abilities must be a list")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Malformed patron ability")
        for key in ("id", "name"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"Malformed patron ability {key}")
        for key in ("eligible", "available", "spent"):
            if type(row.get(key)) is not bool:
                raise ValueError(f"Malformed patron ability {key}")
        for key, vocabulary in (
            ("tier", ("Acknowledged", "Devoted", "Exalted")),
            ("recharge", ("always", "short_rest", "long_rest", "per_session")),
            ("status", ("active", "pending")),
            ("state", ("ready", "spent", "locked")),
        ):
            if row.get(key) not in vocabulary:
                raise ValueError(f"Malformed patron ability {key}")
        if "reason" not in row or (row["reason"] is not None and not isinstance(row["reason"], str)):
            raise ValueError("Malformed patron ability reason")
