from datetime import UTC, datetime, timedelta

import pytest

from favor_rules import apply_favor_delta, neglect_decay


@pytest.mark.parametrize(
    ("level", "cap", "amount", "expected"),
    [
        (-3, 100, 0, 0),
        (0, 100, -5, 0),
        (0, 100, 5, 5),
        (2, 100, -5, 0),
        (10, 100, -3, 7),
        (10, 100, 5, 15),
        (100, 100, 0, 100),
        (100, 100, 5, 100),
        (105, 100, -3, 100),
        (105, 100, -10, 95),
    ],
)
def test_apply_favor_delta(level, cap, amount, expected):
    result = apply_favor_delta(level, cap, amount)
    assert result == expected
    assert 0 <= result <= cap
    if 0 <= level + amount <= cap:
        assert result == level + amount


def test_nonpositive_cap_is_invalid():
    with pytest.raises(ValueError):
        apply_favor_delta(0, 0, 1)


NOW = datetime(2026, 9, 23, tzinfo=UTC)


@pytest.mark.parametrize("field", ["last_served_at", "last_decay_at"])
@pytest.mark.parametrize(
    "age, expected",
    [(timedelta(days=6, hours=23), 0), (timedelta(days=7), 5), (timedelta(days=8), 5), (timedelta(days=40), 5)],
)
def test_decay_uses_single_timestamp(field, age, expected):
    assert neglect_decay({field: (NOW - age).isoformat()}, NOW) == expected


def test_decay_uses_newer_timestamp_in_either_field():
    old = (NOW - timedelta(days=40)).isoformat()
    recent = (NOW - timedelta(days=6)).isoformat()
    assert neglect_decay({"last_served_at": old, "last_decay_at": recent}, NOW) == 0
    assert neglect_decay({"last_served_at": recent, "last_decay_at": old}, NOW) == 0


def test_legacy_row_has_no_decay_due():
    assert neglect_decay({}, NOW) == 0


def test_offset_timestamp_is_normalized():
    assert neglect_decay({"last_served_at": "2026-09-16T02:00:00+02:00"}, NOW) == 5


@pytest.mark.parametrize("field", ["last_served_at", "last_decay_at"])
@pytest.mark.parametrize("bad", ["garbage", "2026-09-16T00:00:00", "2026-09-24T00:00:00+00:00"])
def test_bad_timestamp_raises_even_when_other_field_is_valid(field, bad):
    other = "last_decay_at" if field == "last_served_at" else "last_served_at"
    with pytest.raises(ValueError, match=field):
        neglect_decay({field: bad, other: NOW.isoformat()}, NOW)


def test_naive_now_is_invalid():
    with pytest.raises(ValueError):
        neglect_decay({}, NOW.replace(tzinfo=None))
