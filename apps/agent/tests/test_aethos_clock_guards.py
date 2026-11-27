from datetime import datetime, timedelta, tzinfo

import pytest

from aethos_clock import aethos_day


class NoOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None


@pytest.mark.parametrize("zone", [None, NoOffset()])
def test_aethos_day_rejects_timezone_less_instants(zone: tzinfo | None) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        aethos_day(datetime(2026, 1, 1, tzinfo=zone))


def test_aethos_day_accepts_an_aware_instant_with_an_offset() -> None:
    assert aethos_day(datetime.fromisoformat("2026-01-01T06:00:00-05:00")) == 1
