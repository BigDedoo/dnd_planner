"""Temporary Phase 1 name-shaped API queries for the PostgreSQL runtime.

These operations intentionally mirror the five existing compatibility routes.
They are scheduled for replacement by scoped, ID-shaped APIs in Phase 2.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from .legacy_contract import DOMAIN_TO_LEGACY_STATUS, GROUPS, LEGACY_TO_DOMAIN_STATUS
from .models import Availability, AvailabilityStatus, Group, GroupMembership, User


class CompatibilityError(RuntimeError):
    """Base class for safe compatibility-runtime failures."""


class CompatibilityInputError(CompatibilityError):
    """A name-shaped request cannot resolve to one valid relational identity."""


class CompatibilityDatasetError(CompatibilityError):
    """The imported compatibility dataset cannot safely serve the legacy API."""


class CompatibilityPersistenceError(CompatibilityError):
    """A write failed without exposing database implementation details."""


INPUT_TO_DATABASE_STATUS = {
    legacy_status: AvailabilityStatus(database_status)
    for legacy_status, database_status in LEGACY_TO_DOMAIN_STATUS.items()
}


def _matching_groups(session: Session, name: str) -> list[Group]:
    statement = sa.select(Group).where(Group.name == name).limit(2)
    return list(session.scalars(statement))


def _resolve_group(
    session: Session,
    name: str,
    *,
    allow_missing: bool = False,
) -> Group | None:
    groups = _matching_groups(session, name)
    if not groups and allow_missing:
        return None
    if not groups:
        raise CompatibilityInputError("Unknown group")
    if len(groups) != 1:
        raise CompatibilityInputError("Ambiguous group identity")
    return groups[0]


def _resolve_user(session: Session, display_name: str) -> User:
    statement = sa.select(User).where(User.display_name == display_name).limit(2)
    users = list(session.scalars(statement))
    if not users:
        raise CompatibilityInputError("Unknown user")
    if len(users) != 1:
        raise CompatibilityInputError("Ambiguous user identity")
    return users[0]


def _ordered_players(session: Session, group_id: Any) -> list[str]:
    statement = (
        sa.select(User.display_name)
        .join(GroupMembership, GroupMembership.user_id == User.id)
        .where(GroupMembership.group_id == group_id)
        .order_by(GroupMembership.display_order)
    )
    return list(session.scalars(statement))


def _legacy_status(value: AvailabilityStatus | str) -> str:
    database_value = (
        value.value if isinstance(value, AvailabilityStatus) else str(value)
    )
    try:
        return DOMAIN_TO_LEGACY_STATUS[database_value]
    except KeyError:
        raise CompatibilityDatasetError(
            "Availability contains an unsupported status"
        ) from None


def validate_compatibility_dataset(session: Session) -> None:
    """Require the exact three legacy group projections before serving traffic."""
    for expected_name, expected_players in GROUPS.items():
        groups = _matching_groups(session, expected_name)
        if not groups:
            raise CompatibilityDatasetError(
                f"Expected compatibility group is missing: {expected_name}"
            )
        if len(groups) != 1:
            raise CompatibilityDatasetError(
                f"Expected compatibility group is ambiguous: {expected_name}"
            )
        players = _ordered_players(session, groups[0].id)
        if players != list(expected_players):
            raise CompatibilityDatasetError(
                f"Compatibility membership projection does not match: {expected_name}"
            )


def get_groups(session: Session) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for expected_name in GROUPS:
        matches = _matching_groups(session, expected_name)
        if len(matches) != 1:
            raise CompatibilityDatasetError(
                "Expected compatibility groups are missing or ambiguous"
            )
        groups.append(
            {
                "name": expected_name,
                "players": _ordered_players(session, matches[0].id),
            }
        )
    return groups


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    first_day = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return first_day, next_month


def get_group_month_availability(
    session: Session,
    group_name: str,
    year: int,
    month: int,
) -> list[dict[str, str]]:
    first_day, next_month = _month_bounds(year, month)
    group = _resolve_group(session, group_name, allow_missing=True)
    if group is None:
        return []

    statement = (
        sa.select(User.display_name, Availability.day, Availability.status)
        .select_from(Availability)
        .join(GroupMembership, GroupMembership.user_id == Availability.user_id)
        .join(User, User.id == Availability.user_id)
        .where(
            GroupMembership.group_id == group.id,
            Availability.day >= first_day,
            Availability.day < next_month,
        )
    )
    return [
        {
            "group_name": group_name,
            "user_name": user_name,
            "date": day.isoformat(),
            "status": _legacy_status(status),
        }
        for user_name, day, status in session.execute(statement)
    ]


def _after_availability_mutation(session: Session) -> None:
    """Test seam for proving that request transaction failures roll back."""
    del session


def set_user_availability(
    session: Session,
    group_name: str,
    user_name: str,
    day: date,
    status: str | None,
) -> None:
    try:
        with session.begin():
            group = _resolve_group(session, group_name)
            assert group is not None
            user = _resolve_user(session, user_name)
            membership = session.get(GroupMembership, (group.id, user.id))
            if membership is None:
                raise CompatibilityInputError("User is not a member of the group")

            if status is None:
                statement = sa.delete(Availability).where(
                    Availability.user_id == user.id,
                    Availability.day == day,
                )
            else:
                try:
                    database_status = INPUT_TO_DATABASE_STATUS[status]
                except KeyError:
                    raise CompatibilityInputError(
                        "Status must be Available, Maybe, No, or null"
                    ) from None
                statement = postgresql_insert(Availability).values(
                    user_id=user.id,
                    day=day,
                    status=database_status,
                    updated_at=datetime.now(timezone.utc),
                )
                statement = statement.on_conflict_do_update(
                    index_elements=[Availability.user_id, Availability.day],
                    set_={
                        "status": database_status,
                        "updated_at": sa.func.now(),
                    },
                )
            session.execute(statement)
            _after_availability_mutation(session)
    except CompatibilityInputError:
        raise
    except Exception:
        raise CompatibilityPersistenceError(
            "Availability mutation could not be completed"
        ) from None


def get_all_availability(
    session: Session,
    start: date,
    end: date,
) -> list[dict[str, str]]:
    statement = (
        sa.select(
            Group.name,
            User.display_name,
            Availability.day,
            Availability.status,
        )
        .select_from(Availability)
        .join(GroupMembership, GroupMembership.user_id == Availability.user_id)
        .join(Group, Group.id == GroupMembership.group_id)
        .join(User, User.id == Availability.user_id)
        .where(Availability.day >= start, Availability.day <= end)
    )
    return [
        {
            "group_name": group_name,
            "user_name": user_name,
            "date": day.isoformat(),
            "status": _legacy_status(status),
        }
        for group_name, user_name, day, status in session.execute(statement)
    ]
