"""Session wall times belong to the group zone; durations are elapsed minutes.

Availability and all-day sessions stay date-only. Never guess a DST fold or gap.
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate_timezone(value: str) -> str:
    name = value.strip()
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            "Use a valid IANA timezone, such as Europe/Paris or UTC"
        ) from exc
    return name


def session_utc_range(
    day: date,
    start_time: time | None,
    duration_minutes: int | None,
    group_timezone: str,
) -> tuple[datetime | None, datetime | None]:
    if start_time is None and duration_minutes is None:
        return None, None
    if start_time is None or duration_minutes is None:
        raise ValueError("start_time and duration_minutes must be provided together")
    if start_time.tzinfo is not None:
        raise ValueError(
            "Use a local start_time without an offset; the group timezone applies"
        )
    zone = ZoneInfo(validate_timezone(group_timezone))
    wall_time = datetime.combine(day, start_time)
    candidates = set()
    for fold in (0, 1):
        instant = wall_time.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if instant.astimezone(zone).replace(tzinfo=None) == wall_time:
            candidates.add(instant)
    if len(candidates) != 1:
        problem = "nonexistent" if not candidates else "ambiguous"
        raise ValueError(
            f"Session time {wall_time.isoformat()} is {problem} in {zone.key} "
            "due to a clock change. Choose another local start time."
        )
    start_utc = candidates.pop()
    return start_utc, start_utc + timedelta(minutes=duration_minutes)
