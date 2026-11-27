import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

_CLOCK = json.loads((Path(__file__).resolve().parents[2] / "content/world_clock.json").read_text())
AETHOS_EPOCH = datetime.fromisoformat(_CLOCK["epoch"])
_FIRST_DAWN = AETHOS_EPOCH.astimezone(UTC) + timedelta(hours=_CLOCK["day_start_hour"])
_DAY = timedelta(days=1)


def aethos_day(instant: datetime) -> int:
    """Return the civil day number of the most recent Aethos dawn."""
    if instant.utcoffset() is None:
        raise ValueError("Aethos day requires a timezone-aware datetime")
    return 1 + (instant.astimezone(UTC) - _FIRST_DAWN) // _DAY
