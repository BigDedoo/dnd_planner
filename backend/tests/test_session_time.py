from datetime import date, time, timedelta
from zoneinfo import ZoneInfo, reset_tzpath

import pytest

from backend.session_time import session_utc_range, validate_timezone


@pytest.mark.parametrize("name", ["Europe/Paris", "UTC", "America/New_York"])
def test_valid_timezone(name):
    assert validate_timezone(name) == name


@pytest.mark.parametrize("name", ["Not/AZone", " ", "/etc/passwd", "../UTC"])
def test_invalid_timezone(name):
    with pytest.raises(ValueError, match="valid IANA timezone"):
        validate_timezone(name)


@pytest.mark.parametrize(
    "day,expected",
    [
        (date(2026, 8, 29), "2026-08-29T18:00:00+00:00"),
        (date(2026, 12, 12), "2026-12-12T19:00:00+00:00"),
    ],
)
def test_paris_utc_and_elapsed_duration(day, expected):
    start, end = session_utc_range(day, time(20), 180, "Europe/Paris")
    assert start.isoformat() == expected
    assert end - start == timedelta(minutes=180)


@pytest.mark.parametrize(
    "day,problem",
    [(date(2026, 3, 29), "nonexistent"), (date(2026, 10, 25), "ambiguous")],
)
def test_dst_gap_and_fold_rejected(day, problem):
    with pytest.raises(ValueError, match=problem):
        session_utc_range(day, time(2, 30), 180, "Europe/Paris")


@pytest.mark.parametrize(
    "day,expected_end",
    [
        (date(2026, 3, 29), "2026-03-29T03:30:00+00:00"),
        (date(2026, 10, 25), "2026-10-25T02:30:00+00:00"),
    ],
)
def test_duration_crossing_dst_is_elapsed_not_wall_minutes(day, expected_end):
    start, end = session_utc_range(day, time(1, 30), 180, "Europe/Paris")
    assert end - start == timedelta(minutes=180)
    assert end.isoformat() == expected_end


def test_all_day_has_no_utc_instant():
    assert session_utc_range(date(2026, 3, 29), None, None, "Europe/Paris") == (
        None,
        None,
    )


def test_packaged_timezone_data_without_system_zoneinfo():
    # Exercise the tzdata fallback required by minimal production images.
    ZoneInfo.clear_cache()
    reset_tzpath(())
    try:
        assert validate_timezone("Europe/Paris") == "Europe/Paris"
    finally:
        ZoneInfo.clear_cache()
        reset_tzpath()
