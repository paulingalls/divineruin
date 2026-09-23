"""Pure divine favor rules."""

from datetime import datetime, timedelta


def apply_favor_delta(level: int, max_level: int, amount: int) -> int:
    if max_level <= 0:
        raise ValueError("max_level must be positive")
    if level < 0 or level > max_level:
        raise ValueError(f"level must be between 0 and {max_level}, got {level}")
    return max(0, min(level + amount, max_level))


def neglect_decay(favor: dict, now: datetime) -> int:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must have a timezone")

    timestamps = []
    for field in ("last_served_at", "last_decay_at"):
        if field not in favor:
            continue
        try:
            instant = datetime.fromisoformat(favor[field])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid {field}") from exc
        if instant.tzinfo is None or instant.utcoffset() is None or instant > now:
            raise ValueError(f"invalid {field}")
        timestamps.append(instant)

    if not timestamps:
        return 0
    return 5 if now - max(timestamps) >= timedelta(days=7) else 0
