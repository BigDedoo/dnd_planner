"""Effective, membership-scoped group availability reads and transitions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .models import (
    Availability,
    AvailabilityMode,
    AvailabilityStatus,
    GroupAvailability,
    GroupMembership,
    User,
)


@dataclass(frozen=True)
class EffectiveAvailability:
    user_id: uuid.UUID
    user_name: str
    day: date
    status: AvailabilityStatus


def effective_group_availability(
    session: Session, group_id: uuid.UUID, start: date, end: date
) -> list[EffectiveAvailability]:
    """Use exactly one store per member; never fall back by date."""
    members = session.execute(
        sa.select(User, GroupMembership)
        .join(GroupMembership, GroupMembership.user_id == User.id)
        .where(GroupMembership.group_id == group_id)
    ).all()
    global_names = {
        user.id: membership.nickname or user.display_name
        for user, membership in members
        if membership.availability_mode == AvailabilityMode.GLOBAL
    }
    separate_names = {
        user.id: membership.nickname or user.display_name
        for user, membership in members
        if membership.availability_mode == AvailabilityMode.SEPARATE
    }
    result: list[EffectiveAvailability] = []
    if global_names:
        result.extend(
            EffectiveAvailability(
                row.user_id, global_names[row.user_id], row.day, row.status
            )
            for row in session.scalars(
                sa.select(Availability).where(
                    Availability.user_id.in_(global_names),
                    Availability.day.between(start, end),
                )
            )
        )
    if separate_names:
        result.extend(
            EffectiveAvailability(
                row.user_id, separate_names[row.user_id], row.day, row.status
            )
            for row in session.scalars(
                sa.select(GroupAvailability).where(
                    GroupAvailability.group_id == group_id,
                    GroupAvailability.user_id.in_(separate_names),
                    GroupAvailability.day.between(start, end),
                )
            )
        )
    return sorted(result, key=lambda row: (row.day, row.user_name, row.user_id))


def set_availability_mode(
    session: Session, membership: GroupMembership, mode: AvailabilityMode
) -> GroupMembership:
    """Caller owns the transaction and must hold this membership's row lock."""
    if membership.availability_mode == mode:
        return membership
    if (
        mode == AvailabilityMode.SEPARATE
        and not membership.separate_availability_initialized
    ):
        rows = session.scalars(
            sa.select(Availability).where(Availability.user_id == membership.user_id)
        ).all()
        session.add_all(
            GroupAvailability(
                group_id=membership.group_id,
                user_id=membership.user_id,
                day=row.day,
                status=row.status,
                updated_at=row.updated_at,
            )
            for row in rows
        )
        membership.separate_availability_initialized = True
    membership.availability_mode = mode
    session.flush()
    return membership
