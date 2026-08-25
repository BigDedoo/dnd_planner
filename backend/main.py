"""Authenticated DnD Planner FastAPI application."""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, NoReturn

import sqlalchemy as sa
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import get_current_account, get_current_dnd_user
from .config import Settings, settings
from .db import (
    DatabaseRuntime,
    create_required_database_runtime,
    get_request_session,
    validate_database_readiness,
    validate_injected_runtime,
)
from .group_service import (
    MembershipNotFoundError,
    OwnerInvariantError,
    delete_group,
    remove_member,
    transfer_ownership,
)
from .invites import (
    INVITE_CODE_ALPHABET,
    INVITE_CODE_LENGTH,
    InviteJoinRateLimiter,
    generate_invite_code,
    hash_invite_code,
    normalize_invite_code,
)
from .models import (
    Account,
    Availability,
    AvailabilityStatus,
    ConfirmedSession,
    Group,
    GroupInvite,
    GroupMembership,
    MembershipRole,
    SessionNotificationKind,
    SessionRsvp,
    SessionRsvpStatus,
    User,
)
from .notifications import record_group_notification

logger = logging.getLogger(__name__)
router = APIRouter()


class AccountResponse(BaseModel):
    id: uuid.UUID
    email: str | None = None
    username: str | None = None
    display_name: str | None = None


class MyGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    timezone: str
    role: str
    member_count: int


class GroupMemberResponse(BaseModel):
    id: uuid.UUID
    display_name: str
    nickname: str | None = None
    role: str
    display_order: int


class GroupDetailResponse(BaseModel):
    id: uuid.UUID
    name: str
    timezone: str
    role: str
    current_user_id: uuid.UUID
    members: list[GroupMemberResponse]


class MemberAvailabilityEntry(BaseModel):
    group_name: str
    user_name: str
    user_id: uuid.UUID
    date: str
    status: Literal["Available", "Maybe", "No"]


class AuthenticatedAvailabilityUpdate(BaseModel):
    date: date
    status: Literal["Available", "Maybe", "No"] | None


class ConfirmedSessionResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    day: date
    confirmed_by_user_id: uuid.UUID
    confirmed_at: datetime
    title: str | None = None
    start_time: time | None = None
    duration_minutes: int | None = None
    notes: str | None = None
    updated_at: datetime
    cancelled_at: datetime | None = None
    cancelled_by_user_id: uuid.UUID | None = None
    my_rsvp: Literal["going", "maybe", "declined"] | None = None
    rsvps: list["SessionRsvpResponse"] = Field(default_factory=list)


class SessionRsvpResponse(BaseModel):
    user_id: uuid.UUID
    display_name: str
    status: Literal["going", "maybe", "declined"]
    responded_at: datetime


class MyConfirmedSessionResponse(ConfirmedSessionResponse):
    group_name: str


class SessionDetailsRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    start_time: time | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=1440)
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def require_time_and_duration_together(self) -> "SessionDetailsRequest":
        has_start_time = "start_time" in self.model_fields_set
        has_duration = "duration_minutes" in self.model_fields_set
        if (
            has_start_time
            and has_duration
            and (self.start_time is None) != (self.duration_minutes is None)
        ):
            raise ValueError(
                "start_time and duration_minutes must be provided together"
            )
        return self


class SessionRsvpRequest(BaseModel):
    status: Literal["going", "maybe", "declined"]


class CreateGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    nickname: str | None = Field(default=None, max_length=120)


class GroupMutationResponse(BaseModel):
    id: uuid.UUID
    name: str
    timezone: str
    role: str


class GroupInviteCodeResponse(BaseModel):
    code: str
    created_at: datetime
    use_count: int


class GroupInviteStatusResponse(BaseModel):
    active: bool
    created_at: datetime | None = None
    use_count: int | None = None


class JoinGroupRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    nickname: str | None = Field(default=None, max_length=120)


class JoinGroupResponse(GroupMutationResponse):
    joined: bool


class InvitePreviewRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class InvitePreviewResponse(BaseModel):
    group_name: str


class OnboardingStatusResponse(BaseModel):
    linked: bool
    suggested_display_name: str | None = None
    user_id: uuid.UUID | None = None


class OnboardingRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class UpdateOwnGroupMembershipRequest(BaseModel):
    nickname: str | None = Field(default=None, max_length=120)


class UpdateGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class UpdateGroupMemberRoleRequest(BaseModel):
    role: Literal["organizer", "member"]


class TransferGroupOwnershipRequest(BaseModel):
    user_id: uuid.UUID


def get_authorized_membership(
    group_id: uuid.UUID,
    user: User = Depends(get_current_dnd_user),
    session: Session = Depends(get_request_session),
) -> tuple[Group, GroupMembership, User]:
    membership = session.scalars(
        select(GroupMembership).where(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == user.id,
        )
    ).first()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this group",
        )
    group = session.get(Group, group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )
    return group, membership, user


def _require_group_owner(
    auth_data: tuple[Group, GroupMembership, User],
) -> tuple[Group, GroupMembership, User]:
    if auth_data[1].role != MembershipRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only group owners can manage this group",
        )
    return auth_data


def _require_group_owner_or_organizer(
    auth_data: tuple[Group, GroupMembership, User],
) -> tuple[Group, GroupMembership, User]:
    if auth_data[1].role not in {MembershipRole.OWNER, MembershipRole.ORGANIZER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only group owners and organizers can manage members",
        )
    return auth_data


def _group_member_response(membership: GroupMembership) -> GroupMemberResponse:
    return GroupMemberResponse(
        id=membership.user_id,
        display_name=_effective_group_display_name(membership.user, membership),
        nickname=membership.nickname,
        role=membership.role.value,
        display_order=membership.display_order,
    )


def _validate_date_range(start: date, end: date) -> None:
    if start > end:
        raise HTTPException(
            status_code=422,
            detail="start date must be before or equal to end date",
        )


def _normalized_optional_nickname(value: str | None) -> str | None:
    if value is None:
        return None
    nickname = value.strip()
    return nickname or None


def _effective_group_display_name(user: User, membership: GroupMembership) -> str:
    return membership.nickname or user.display_name


def _confirmed_session_response(
    db_session: Session,
    confirmed_session: ConfirmedSession,
    *,
    current_user_id: uuid.UUID,
    group_name: str | None = None,
    include_rsvps: bool = True,
) -> ConfirmedSessionResponse | MyConfirmedSessionResponse:
    rsvps: list[SessionRsvpResponse] = []
    my_rsvp: str | None = None
    rows = db_session.execute(
        select(SessionRsvp, User, GroupMembership)
        .join(User, User.id == SessionRsvp.user_id)
        .outerjoin(
            GroupMembership,
            sa.and_(
                GroupMembership.group_id == confirmed_session.group_id,
                GroupMembership.user_id == SessionRsvp.user_id,
            ),
        )
        .where(SessionRsvp.session_id == confirmed_session.id)
        .order_by(User.display_name, SessionRsvp.user_id)
    ).all()
    for rsvp, rsvp_user, membership in rows:
        if rsvp.user_id == current_user_id:
            my_rsvp = rsvp.status.value
        if include_rsvps:
            rsvps.append(
                SessionRsvpResponse(
                    user_id=rsvp.user_id,
                    display_name=_effective_group_display_name(rsvp_user, membership)
                    if membership is not None
                    else rsvp_user.display_name,
                    status=rsvp.status.value,
                    responded_at=rsvp.responded_at,
                )
            )
    payload = {
        "id": confirmed_session.id,
        "group_id": confirmed_session.group_id,
        "day": confirmed_session.day,
        "confirmed_by_user_id": confirmed_session.confirmed_by_user_id,
        "confirmed_at": confirmed_session.confirmed_at,
        "title": confirmed_session.title,
        "start_time": confirmed_session.start_time,
        "duration_minutes": confirmed_session.duration_minutes,
        "notes": confirmed_session.notes,
        "updated_at": confirmed_session.updated_at,
        "cancelled_at": confirmed_session.cancelled_at,
        "cancelled_by_user_id": confirmed_session.cancelled_by_user_id,
        "my_rsvp": my_rsvp,
        "rsvps": rsvps,
    }
    if group_name is not None:
        return MyConfirmedSessionResponse(group_name=group_name, **payload)
    return ConfirmedSessionResponse(**payload)


def _apply_session_details(
    confirmed_session: ConfirmedSession,
    details: SessionDetailsRequest,
) -> None:
    if "title" in details.model_fields_set:
        confirmed_session.title = (
            details.title.strip() if details.title and details.title.strip() else None
        )
    if "notes" in details.model_fields_set:
        confirmed_session.notes = (
            details.notes.strip() if details.notes and details.notes.strip() else None
        )
    if "start_time" in details.model_fields_set:
        confirmed_session.start_time = details.start_time
    if "duration_minutes" in details.model_fields_set:
        confirmed_session.duration_minutes = details.duration_minutes
    if (confirmed_session.start_time is None) != (
        confirmed_session.duration_minutes is None
    ):
        raise HTTPException(
            status_code=422,
            detail="start_time and duration_minutes must be provided together",
        )


def _ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _session_ics_event(confirmed_session: ConfirmedSession, group: Group) -> list[str]:
    title = confirmed_session.title or f"Session — {group.name}"
    lines = [
        "BEGIN:VEVENT",
        f"UID:{confirmed_session.id}@dnd-planner",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{_ics_escape(title)}",
        f"DESCRIPTION:{_ics_escape(confirmed_session.notes or '')}",
    ]
    if confirmed_session.start_time and confirmed_session.duration_minutes:
        starts_at = datetime.combine(
            confirmed_session.day, confirmed_session.start_time
        )
        ends_at = starts_at + timedelta(minutes=confirmed_session.duration_minutes)
        lines.extend(
            [
                f"DTSTART;TZID={group.timezone}:{starts_at.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID={group.timezone}:{ends_at.strftime('%Y%m%dT%H%M%S')}",
            ]
        )
    else:
        lines.extend(
            [
                f"DTSTART;VALUE=DATE:{confirmed_session.day.strftime('%Y%m%d')}",
                "DTEND;VALUE=DATE:"
                f"{(confirmed_session.day + timedelta(days=1)).strftime('%Y%m%d')}",
            ]
        )
    lines.append("END:VEVENT")
    return lines


def _calendar_response(events: list[tuple[ConfirmedSession, Group]], filename: str):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//DnD Planner//Sessions//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for confirmed_session, group in events:
        lines.extend(_session_ics_event(confirmed_session, group))
    lines.append("END:VCALENDAR")
    return Response(
        content="\r\n".join(lines) + "\r\n",
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/me", response_model=AccountResponse)
@router.get("/api/me", response_model=AccountResponse)
def get_me(account: Account = Depends(get_current_account)):
    return AccountResponse(
        id=account.id,
        email=account.email,
        username=account.username,
        display_name=account.display_name,
    )


@router.get("/onboarding", response_model=OnboardingStatusResponse)
@router.get("/api/onboarding", response_model=OnboardingStatusResponse)
def get_onboarding_status(
    account: Account = Depends(get_current_account),
    session: Session = Depends(get_request_session),
):
    user = session.scalar(select(User).where(User.account_id == account.id))
    if user is not None:
        return OnboardingStatusResponse(linked=True, user_id=user.id)
    return OnboardingStatusResponse(
        linked=False,
        suggested_display_name=account.username or account.display_name,
    )


@router.post("/onboarding", response_model=OnboardingStatusResponse, status_code=201)
@router.post(
    "/api/onboarding", response_model=OnboardingStatusResponse, status_code=201
)
def complete_onboarding(
    request: Request,
    payload: OnboardingRequest,
    account: Account = Depends(get_current_account),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503, detail="Onboarding is temporarily disabled"
        )

    display_name = payload.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail="Display name cannot be blank")

    existing_user = session.scalar(select(User).where(User.account_id == account.id))
    if existing_user is not None:
        return OnboardingStatusResponse(linked=True, user_id=existing_user.id)

    user = User(account_id=account.id, display_name=display_name)
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing_user = session.scalar(
            select(User).where(User.account_id == account.id)
        )
        if existing_user is not None:
            return OnboardingStatusResponse(linked=True, user_id=existing_user.id)
        raise HTTPException(
            status_code=503,
            detail="Onboarding could not be completed",
        ) from exc
    session.refresh(user)
    return OnboardingStatusResponse(linked=True, user_id=user.id)


@router.get("/me/groups", response_model=list[MyGroupResponse])
@router.get("/api/me/groups", response_model=list[MyGroupResponse])
def get_my_groups(
    user: User = Depends(get_current_dnd_user),
    session: Session = Depends(get_request_session),
):
    stmt = (
        select(Group, GroupMembership.role)
        .join(GroupMembership, GroupMembership.group_id == Group.id)
        .where(GroupMembership.user_id == user.id)
        .order_by(Group.name)
    )
    results = session.execute(stmt).all()
    my_groups = []
    for group, role in results:
        count_stmt = (
            select(sa.func.count())
            .select_from(GroupMembership)
            .where(GroupMembership.group_id == group.id)
        )
        member_count = session.scalar(count_stmt) or 0
        my_groups.append(
            MyGroupResponse(
                id=group.id,
                name=group.name,
                timezone=group.timezone,
                role=role.value,
                member_count=member_count,
            )
        )
    return my_groups


def _group_response(group: Group, role: MembershipRole) -> GroupMutationResponse:
    return GroupMutationResponse(
        id=group.id,
        name=group.name,
        timezone=group.timezone,
        role=role.value,
    )


def _active_invite_group(code: str, session: Session) -> Group | None:
    normalized_code = normalize_invite_code(code)
    if len(normalized_code) != INVITE_CODE_LENGTH or any(
        character not in INVITE_CODE_ALPHABET for character in normalized_code
    ):
        return None

    invite = session.scalar(
        select(GroupInvite).where(
            GroupInvite.code_hash == hash_invite_code(normalized_code),
            GroupInvite.revoked_at.is_(None),
        )
    )
    if invite is None:
        return None
    return session.scalar(select(Group).where(Group.id == invite.group_id))


def _require_invite_attempt(request: Request, user: User) -> InviteJoinRateLimiter:
    limiter: InviteJoinRateLimiter = request.app.state.invite_join_rate_limiter
    if not limiter.allow_attempt(user.id):
        raise HTTPException(
            status_code=429,
            detail="Too many invite-code attempts. Please try again shortly.",
        )
    return limiter


def _invalid_invite(limiter: InviteJoinRateLimiter, user: User) -> NoReturn:
    limiter.record_failure(user.id)
    raise HTTPException(
        status_code=404, detail="Invite code is invalid or has been revoked"
    )


@router.post("/groups", response_model=GroupMutationResponse, status_code=201)
@router.post("/api/groups", response_model=GroupMutationResponse, status_code=201)
def create_group(
    request: Request,
    payload: CreateGroupRequest,
    user: User = Depends(get_current_dnd_user),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503, detail="Group mutations are temporarily disabled"
        )

    name = payload.name.strip()
    group_timezone = payload.timezone.strip()
    description = payload.description.strip() if payload.description else None
    if not name or not group_timezone:
        raise HTTPException(
            status_code=422, detail="Group name and timezone cannot be blank"
        )

    group = Group(name=name, timezone=group_timezone, description=description)
    nickname = _normalized_optional_nickname(payload.nickname)
    session.add(group)
    try:
        session.flush()
        session.add(
            GroupMembership(
                group_id=group.id,
                user_id=user.id,
                role=MembershipRole.OWNER,
                nickname=nickname,
                display_order=0,
            )
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Group creation could not be completed",
        ) from exc
    session.refresh(group)
    return _group_response(group, MembershipRole.OWNER)


@router.get("/groups/{group_id}/invite", response_model=GroupInviteStatusResponse)
@router.get("/api/groups/{group_id}/invite", response_model=GroupInviteStatusResponse)
def get_group_invite_status(
    group_id: uuid.UUID,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    group, _, _ = _require_group_owner(auth_data)
    invite = session.scalar(
        select(GroupInvite).where(
            GroupInvite.group_id == group.id,
            GroupInvite.revoked_at.is_(None),
        )
    )
    if invite is None:
        return GroupInviteStatusResponse(active=False)
    return GroupInviteStatusResponse(
        active=True,
        created_at=invite.created_at,
        use_count=invite.use_count,
    )


@router.post("/groups/{group_id}/invite", response_model=GroupInviteCodeResponse)
@router.post("/api/groups/{group_id}/invite", response_model=GroupInviteCodeResponse)
def generate_group_invite(
    request: Request,
    group_id: uuid.UUID,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503, detail="Invite mutations are temporarily disabled"
        )
    group, _, user = _require_group_owner(auth_data)

    existing = session.scalar(
        select(GroupInvite).where(
            GroupInvite.group_id == group.id,
            GroupInvite.revoked_at.is_(None),
        )
    )
    if existing is not None:
        existing.revoked_at = datetime.now(timezone.utc)

    code = ""
    code_hash = ""
    for _ in range(5):
        code = generate_invite_code()
        code_hash = hash_invite_code(code)
        if (
            session.scalar(
                select(GroupInvite.id).where(GroupInvite.code_hash == code_hash)
            )
            is None
        ):
            break
    else:
        session.rollback()
        raise HTTPException(
            status_code=503, detail="Could not generate a unique invite code"
        )

    invite = GroupInvite(
        group_id=group.id,
        code_hash=code_hash,
        created_by_user_id=user.id,
    )
    session.add(invite)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Invite generation could not be completed",
        ) from exc
    session.refresh(invite)
    return GroupInviteCodeResponse(
        code=code,
        created_at=invite.created_at,
        use_count=invite.use_count,
    )


@router.delete("/groups/{group_id}/invite")
@router.delete("/api/groups/{group_id}/invite")
def revoke_group_invite(
    request: Request,
    group_id: uuid.UUID,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503, detail="Invite mutations are temporarily disabled"
        )
    group, _, _ = _require_group_owner(auth_data)
    invite = session.scalar(
        select(GroupInvite).where(
            GroupInvite.group_id == group.id,
            GroupInvite.revoked_at.is_(None),
        )
    )
    if invite is None:
        raise HTTPException(status_code=404, detail="No active invite code")
    invite.revoked_at = datetime.now(timezone.utc)
    session.commit()
    return {"status": "success"}


@router.post("/group-invites/preview", response_model=InvitePreviewResponse)
@router.post("/api/group-invites/preview", response_model=InvitePreviewResponse)
def preview_group_invite(
    request: Request,
    payload: InvitePreviewRequest,
    user: User = Depends(get_current_dnd_user),
    session: Session = Depends(get_request_session),
):
    limiter = _require_invite_attempt(request, user)
    group = _active_invite_group(payload.code, session)
    if group is None:
        _invalid_invite(limiter, user)
    limiter.clear(user.id)
    return InvitePreviewResponse(group_name=group.name)


@router.post("/groups/join", response_model=JoinGroupResponse)
@router.post("/api/groups/join", response_model=JoinGroupResponse)
def join_group_with_invite(
    request: Request,
    payload: JoinGroupRequest,
    user: User = Depends(get_current_dnd_user),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503, detail="Group mutations are temporarily disabled"
        )

    limiter = _require_invite_attempt(request, user)
    group = _active_invite_group(payload.code, session)
    if group is None:
        _invalid_invite(limiter, user)

    group = session.scalar(select(Group).where(Group.id == group.id).with_for_update())
    if group is None:
        _invalid_invite(limiter, user)
    invite = session.scalar(
        select(GroupInvite).where(
            GroupInvite.group_id == group.id,
            GroupInvite.code_hash == hash_invite_code(payload.code),
            GroupInvite.revoked_at.is_(None),
        )
    )
    if invite is None:
        _invalid_invite(limiter, user)

    existing_membership = session.get(GroupMembership, (group.id, user.id))
    if existing_membership is not None:
        limiter.clear(user.id)
        return JoinGroupResponse(
            **_group_response(group, existing_membership.role).model_dump(),
            joined=False,
        )

    next_display_order = session.scalar(
        select(
            sa.func.coalesce(sa.func.max(GroupMembership.display_order), -1) + 1
        ).where(GroupMembership.group_id == group.id)
    )
    session.add(
        GroupMembership(
            group_id=group.id,
            user_id=user.id,
            role=MembershipRole.MEMBER,
            nickname=_normalized_optional_nickname(payload.nickname),
            display_order=next_display_order,
        )
    )
    invite.use_count += 1
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing_membership = session.get(GroupMembership, (group.id, user.id))
        if existing_membership is not None:
            limiter.clear(user.id)
            return JoinGroupResponse(
                **_group_response(group, existing_membership.role).model_dump(),
                joined=False,
            )
        raise HTTPException(
            status_code=503, detail="Could not join this group"
        ) from exc

    limiter.clear(user.id)
    return JoinGroupResponse(
        **_group_response(group, MembershipRole.MEMBER).model_dump(),
        joined=True,
    )


@router.patch("/groups/{group_id}/me", response_model=GroupMemberResponse)
@router.patch("/api/groups/{group_id}/me", response_model=GroupMemberResponse)
def update_own_group_membership(
    request: Request,
    group_id: uuid.UUID,
    payload: UpdateOwnGroupMembershipRequest,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503, detail="Group membership updates are temporarily disabled"
        )
    _, membership, user = auth_data
    membership.nickname = _normalized_optional_nickname(payload.nickname)
    session.commit()
    return _group_member_response(membership)


@router.patch("/groups/{group_id}", response_model=GroupMutationResponse)
@router.patch("/api/groups/{group_id}", response_model=GroupMutationResponse)
def update_group(
    request: Request,
    group_id: uuid.UUID,
    payload: UpdateGroupRequest,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503, detail="Group mutations are temporarily disabled"
        )
    group, membership, _ = _require_group_owner(auth_data)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Group name cannot be blank")
    group.name = name
    session.commit()
    session.refresh(group)
    return _group_response(group, membership.role)


@router.post("/groups/{group_id}/leave")
@router.post("/api/groups/{group_id}/leave")
def leave_group(
    request: Request,
    group_id: uuid.UUID,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503, detail="Group mutations are temporarily disabled"
        )
    _, membership, user = auth_data
    if membership.role == MembershipRole.OWNER:
        raise HTTPException(
            status_code=409,
            detail="Transfer ownership before leaving this group",
        )
    try:
        remove_member(session, group_id=group_id, user_id=user.id)
        session.commit()
    except OwnerInvariantError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MembershipNotFoundError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "success"}


@router.delete("/groups/{group_id}/members/{member_user_id}")
@router.delete("/api/groups/{group_id}/members/{member_user_id}")
def remove_group_member(
    request: Request,
    group_id: uuid.UUID,
    member_user_id: uuid.UUID,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503, detail="Group mutations are temporarily disabled"
        )
    _, actor_membership, actor = _require_group_owner_or_organizer(auth_data)
    if member_user_id == actor.id:
        raise HTTPException(
            status_code=403,
            detail="Use the leave action to remove yourself from a group",
        )
    target_membership = session.get(GroupMembership, (group_id, member_user_id))
    if target_membership is None:
        raise HTTPException(
            status_code=404, detail="User is not a member of this group"
        )
    if target_membership.role == MembershipRole.OWNER:
        raise HTTPException(
            status_code=409,
            detail="The owner must transfer ownership before leaving the group",
        )
    if (
        actor_membership.role == MembershipRole.ORGANIZER
        and target_membership.role != MembershipRole.MEMBER
    ):
        raise HTTPException(
            status_code=403,
            detail="Organizers can remove ordinary members only",
        )
    try:
        remove_member(session, group_id=group_id, user_id=member_user_id)
        session.commit()
    except OwnerInvariantError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MembershipNotFoundError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "success"}


@router.patch(
    "/groups/{group_id}/members/{member_user_id}/role",
    response_model=GroupMemberResponse,
)
@router.patch(
    "/api/groups/{group_id}/members/{member_user_id}/role",
    response_model=GroupMemberResponse,
)
def update_group_member_role(
    request: Request,
    group_id: uuid.UUID,
    member_user_id: uuid.UUID,
    payload: UpdateGroupMemberRoleRequest,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503, detail="Group mutations are temporarily disabled"
        )
    _require_group_owner(auth_data)
    target_membership = session.get(GroupMembership, (group_id, member_user_id))
    if target_membership is None:
        raise HTTPException(
            status_code=404, detail="User is not a member of this group"
        )
    if target_membership.role == MembershipRole.OWNER:
        raise HTTPException(
            status_code=409,
            detail="The owner cannot be demoted; transfer ownership first",
        )
    target_membership.role = MembershipRole(payload.role)
    session.commit()
    return _group_member_response(target_membership)


@router.post(
    "/groups/{group_id}/transfer-ownership", response_model=GroupMutationResponse
)
@router.post(
    "/api/groups/{group_id}/transfer-ownership",
    response_model=GroupMutationResponse,
)
def transfer_group_ownership(
    request: Request,
    group_id: uuid.UUID,
    payload: TransferGroupOwnershipRequest,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503, detail="Group mutations are temporarily disabled"
        )
    group, _, user = _require_group_owner(auth_data)
    if payload.user_id == user.id:
        raise HTTPException(
            status_code=422,
            detail="Choose another group member as the new owner",
        )
    try:
        transfer_ownership(
            session,
            group_id=group_id,
            current_owner_user_id=user.id,
            new_owner_user_id=payload.user_id,
        )
        session.commit()
    except MembershipNotFoundError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OwnerInvariantError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _group_response(group, MembershipRole.MEMBER)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
@router.delete("/api/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_managed_group(
    request: Request,
    group_id: uuid.UUID,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503, detail="Group mutations are temporarily disabled"
        )
    _require_group_owner(auth_data)
    try:
        delete_group(session, group_id=group_id)
        session.commit()
    except MembershipNotFoundError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/me/confirmed-sessions",
    response_model=list[MyConfirmedSessionResponse],
)
@router.get(
    "/api/me/confirmed-sessions",
    response_model=list[MyConfirmedSessionResponse],
)
def get_my_confirmed_sessions(
    start: date,
    end: date,
    include_cancelled: bool = False,
    user: User = Depends(get_current_dnd_user),
    session: Session = Depends(get_request_session),
):
    _validate_date_range(start, end)
    statement = (
        select(ConfirmedSession, Group.name)
        .join(Group, Group.id == ConfirmedSession.group_id)
        .join(
            GroupMembership,
            GroupMembership.group_id == ConfirmedSession.group_id,
        )
        .where(
            GroupMembership.user_id == user.id,
            ConfirmedSession.day >= start,
            ConfirmedSession.day <= end,
        )
        .order_by(ConfirmedSession.day, Group.name, ConfirmedSession.id)
    )
    if not include_cancelled:
        statement = statement.where(ConfirmedSession.cancelled_at.is_(None))
    rows = session.execute(statement).all()
    return [
        _confirmed_session_response(
            session,
            confirmed_session,
            current_user_id=user.id,
            group_name=group_name,
            include_rsvps=False,
        )
        for confirmed_session, group_name in rows
    ]


@router.get("/me/confirmed-sessions.ics")
@router.get("/api/me/confirmed-sessions.ics")
def export_my_confirmed_sessions(
    start: date | None = None,
    end: date | None = None,
    user: User = Depends(get_current_dnd_user),
    session: Session = Depends(get_request_session),
):
    first_day = start or date.today()
    last_day = end or first_day + timedelta(days=366)
    _validate_date_range(first_day, last_day)
    rows = session.execute(
        select(ConfirmedSession, Group)
        .join(Group, Group.id == ConfirmedSession.group_id)
        .join(
            GroupMembership,
            GroupMembership.group_id == ConfirmedSession.group_id,
        )
        .where(
            GroupMembership.user_id == user.id,
            ConfirmedSession.day >= first_day,
            ConfirmedSession.day <= last_day,
            ConfirmedSession.cancelled_at.is_(None),
        )
        .order_by(ConfirmedSession.day, Group.name)
    ).all()
    return _calendar_response(rows, "dnd-planner-schedule.ics")


@router.get("/groups/{group_id}", response_model=GroupDetailResponse)
@router.get("/api/groups/{group_id}", response_model=GroupDetailResponse)
def get_group_detail(
    group_id: uuid.UUID,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    group, current_membership, current_user = auth_data
    stmt = (
        select(User, GroupMembership)
        .join(GroupMembership, GroupMembership.user_id == User.id)
        .where(GroupMembership.group_id == group.id)
        .order_by(GroupMembership.display_order, User.display_name)
    )
    members_data = session.execute(stmt).all()
    members = [
        GroupMemberResponse(
            id=u.id,
            display_name=_effective_group_display_name(u, gm),
            nickname=gm.nickname,
            role=gm.role.value,
            display_order=gm.display_order,
        )
        for u, gm in members_data
    ]
    return GroupDetailResponse(
        id=group.id,
        name=group.name,
        timezone=group.timezone,
        role=current_membership.role.value,
        current_user_id=current_user.id,
        members=members,
    )


@router.get(
    "/groups/{group_id}/confirmed-sessions",
    response_model=list[ConfirmedSessionResponse],
)
@router.get(
    "/api/groups/{group_id}/confirmed-sessions",
    response_model=list[ConfirmedSessionResponse],
)
def get_group_confirmed_sessions(
    group_id: uuid.UUID,
    start: date,
    end: date,
    include_cancelled: bool = False,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    _validate_date_range(start, end)
    group, _, user = auth_data
    statement = (
        select(ConfirmedSession)
        .where(
            ConfirmedSession.group_id == group.id,
            ConfirmedSession.day >= start,
            ConfirmedSession.day <= end,
        )
        .order_by(ConfirmedSession.day, ConfirmedSession.id)
    )
    if not include_cancelled:
        statement = statement.where(ConfirmedSession.cancelled_at.is_(None))
    sessions = session.scalars(statement).all()
    return [
        _confirmed_session_response(session, confirmed_session, current_user_id=user.id)
        for confirmed_session in sessions
    ]


@router.get("/groups/{group_id}/confirmed-sessions/{day}/calendar.ics")
@router.get("/api/groups/{group_id}/confirmed-sessions/{day}/calendar.ics")
def export_group_session(
    group_id: uuid.UUID,
    day: date,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    group, _, _ = auth_data
    confirmed_session = session.scalar(
        select(ConfirmedSession).where(
            ConfirmedSession.group_id == group.id,
            ConfirmedSession.day == day,
            ConfirmedSession.cancelled_at.is_(None),
        )
    )
    if confirmed_session is None:
        raise HTTPException(status_code=404, detail="Confirmed session not found")
    return _calendar_response(
        [(confirmed_session, group)],
        f"dnd-planner-{confirmed_session.day.isoformat()}.ics",
    )


@router.put(
    "/groups/{group_id}/confirmed-sessions/{day}",
    response_model=ConfirmedSessionResponse,
)
@router.put(
    "/api/groups/{group_id}/confirmed-sessions/{day}",
    response_model=ConfirmedSessionResponse,
)
def confirm_group_session(
    request: Request,
    group_id: uuid.UUID,
    day: date,
    details: SessionDetailsRequest | None = None,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503,
            detail="Confirmed-session mutations are temporarily disabled",
        )
    group, _, user = _require_group_owner_or_organizer(auth_data)
    existing = session.scalar(
        select(ConfirmedSession).where(
            ConfirmedSession.group_id == group.id,
            ConfirmedSession.day == day,
        )
    )
    if existing is not None:
        if existing.cancelled_at is None:
            return _confirmed_session_response(
                session, existing, current_user_id=user.id
            )
        existing.cancelled_at = None
        existing.cancelled_by_user_id = None
        existing.confirmed_by_user_id = user.id
        existing.confirmed_at = datetime.now(timezone.utc)
        if details is not None:
            _apply_session_details(existing, details)
        session.flush()
        record_group_notification(
            session,
            confirmed_session=existing,
            kind=SessionNotificationKind.SCHEDULED,
        )
        session.commit()
        session.refresh(existing)
        return _confirmed_session_response(session, existing, current_user_id=user.id)

    confirmed_session = ConfirmedSession(
        group_id=group.id,
        day=day,
        confirmed_by_user_id=user.id,
    )
    if details is not None:
        _apply_session_details(confirmed_session, details)
    session.add(confirmed_session)
    try:
        session.flush()
        record_group_notification(
            session,
            confirmed_session=confirmed_session,
            kind=SessionNotificationKind.SCHEDULED,
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(ConfirmedSession).where(
                ConfirmedSession.group_id == group.id,
                ConfirmedSession.day == day,
            )
        )
        if existing is None:
            raise
        return _confirmed_session_response(session, existing, current_user_id=user.id)
    session.refresh(confirmed_session)
    return _confirmed_session_response(
        session, confirmed_session, current_user_id=user.id
    )


@router.patch(
    "/groups/{group_id}/confirmed-sessions/{day}",
    response_model=ConfirmedSessionResponse,
)
@router.patch(
    "/api/groups/{group_id}/confirmed-sessions/{day}",
    response_model=ConfirmedSessionResponse,
)
def update_group_session(
    request: Request,
    group_id: uuid.UUID,
    day: date,
    details: SessionDetailsRequest,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503,
            detail="Confirmed-session mutations are temporarily disabled",
        )
    group, _, user = _require_group_owner_or_organizer(auth_data)
    confirmed_session = session.scalar(
        select(ConfirmedSession).where(
            ConfirmedSession.group_id == group.id,
            ConfirmedSession.day == day,
        )
    )
    if confirmed_session is None:
        raise HTTPException(status_code=404, detail="Confirmed session not found")
    if confirmed_session.cancelled_at is not None:
        raise HTTPException(
            status_code=409, detail="Cancelled sessions cannot be edited"
        )
    _apply_session_details(confirmed_session, details)
    confirmed_session.updated_at = datetime.now(timezone.utc)
    session.flush()
    record_group_notification(
        session,
        confirmed_session=confirmed_session,
        kind=SessionNotificationKind.CHANGED,
    )
    session.commit()
    session.refresh(confirmed_session)
    return _confirmed_session_response(
        session, confirmed_session, current_user_id=user.id
    )


@router.put(
    "/groups/{group_id}/confirmed-sessions/{day}/rsvp",
    response_model=ConfirmedSessionResponse,
)
@router.put(
    "/api/groups/{group_id}/confirmed-sessions/{day}/rsvp",
    response_model=ConfirmedSessionResponse,
)
def update_own_session_rsvp(
    request: Request,
    group_id: uuid.UUID,
    day: date,
    payload: SessionRsvpRequest,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503,
            detail="Confirmed-session mutations are temporarily disabled",
        )
    group, _, user = auth_data
    confirmed_session = session.scalar(
        select(ConfirmedSession).where(
            ConfirmedSession.group_id == group.id,
            ConfirmedSession.day == day,
        )
    )
    if confirmed_session is None:
        raise HTTPException(status_code=404, detail="Confirmed session not found")
    if confirmed_session.cancelled_at is not None:
        raise HTTPException(
            status_code=409, detail="Cancelled sessions do not accept RSVPs"
        )
    rsvp = session.get(SessionRsvp, (confirmed_session.id, user.id))
    if rsvp is None:
        rsvp = SessionRsvp(
            session_id=confirmed_session.id,
            user_id=user.id,
            status=SessionRsvpStatus(payload.status),
        )
        session.add(rsvp)
    else:
        rsvp.status = SessionRsvpStatus(payload.status)
    session.commit()
    session.refresh(confirmed_session)
    return _confirmed_session_response(
        session, confirmed_session, current_user_id=user.id
    )


@router.delete("/groups/{group_id}/confirmed-sessions/{day}")
@router.delete("/api/groups/{group_id}/confirmed-sessions/{day}")
def cancel_group_session(
    request: Request,
    group_id: uuid.UUID,
    day: date,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503,
            detail="Confirmed-session mutations are temporarily disabled",
        )
    group, _, user = _require_group_owner_or_organizer(auth_data)
    confirmed_session = session.scalar(
        select(ConfirmedSession).where(
            ConfirmedSession.group_id == group.id,
            ConfirmedSession.day == day,
        )
    )
    if confirmed_session is None:
        raise HTTPException(status_code=404, detail="Confirmed session not found")
    if confirmed_session.cancelled_at is not None:
        return {"status": "success"}
    now = datetime.now(timezone.utc)
    confirmed_session.cancelled_at = now
    confirmed_session.cancelled_by_user_id = user.id
    confirmed_session.updated_at = now
    session.flush()
    record_group_notification(
        session,
        confirmed_session=confirmed_session,
        kind=SessionNotificationKind.CANCELLED,
    )
    session.commit()
    return {"status": "success"}


@router.get(
    "/groups/{group_id}/availability/{year}/{month}",
    response_model=list[MemberAvailabilityEntry],
)
@router.get(
    "/api/groups/{group_id}/availability/{year}/{month}",
    response_model=list[MemberAvailabilityEntry],
)
def get_authenticated_group_month_availability(
    group_id: uuid.UUID,
    year: int,
    month: int,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    if year < 2000 or year > 2100 or month < 1 or month > 12:
        raise HTTPException(status_code=422, detail="Invalid year or month")

    group, _, _ = auth_data
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)

    members_stmt = (
        select(User, GroupMembership)
        .join(GroupMembership, GroupMembership.user_id == User.id)
        .where(GroupMembership.group_id == group.id)
    )
    members = session.execute(members_stmt).all()
    user_map = {
        member.id: _effective_group_display_name(member, membership)
        for member, membership in members
    }
    if not user_map:
        return []

    avail_stmt = select(Availability).where(
        Availability.user_id.in_(user_map.keys()),
        Availability.day >= start_date,
        Availability.day <= end_date,
    )
    avail_entries = session.scalars(avail_stmt).all()

    status_map = {
        AvailabilityStatus.AVAILABLE: "Available",
        AvailabilityStatus.MAYBE: "Maybe",
        AvailabilityStatus.UNAVAILABLE: "No",
    }

    return [
        MemberAvailabilityEntry(
            group_name=group.name,
            user_name=user_map[entry.user_id],
            user_id=entry.user_id,
            date=entry.day.isoformat(),
            status=status_map[entry.status],
        )
        for entry in avail_entries
        if entry.user_id in user_map
    ]


@router.post("/groups/{group_id}/availability")
@router.post("/api/groups/{group_id}/availability")
def update_authenticated_group_availability(
    request: Request,
    group_id: uuid.UUID,
    update: AuthenticatedAvailabilityUpdate,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503,
            detail="Availability mutations are temporarily disabled",
        )
    _, _, user = auth_data

    domain_status_map = {
        "Available": AvailabilityStatus.AVAILABLE,
        "Maybe": AvailabilityStatus.MAYBE,
        "No": AvailabilityStatus.UNAVAILABLE,
    }

    if update.status is None:
        stmt = sa.delete(Availability).where(
            Availability.user_id == user.id,
            Availability.day == update.date,
        )
        session.execute(stmt)
    else:
        domain_status = domain_status_map[update.status]
        existing = session.scalars(
            select(Availability).where(
                Availability.user_id == user.id,
                Availability.day == update.date,
            )
        ).first()
        if existing:
            existing.status = domain_status
        else:
            new_entry = Availability(
                user_id=user.id,
                day=update.date,
                status=domain_status,
            )
            session.add(new_entry)

    session.commit()
    return {"status": "success", "new_state": update.status}


@router.get(
    "/groups/{group_id}/admin/availability",
    response_model=list[MemberAvailabilityEntry],
)
@router.get(
    "/api/groups/{group_id}/admin/availability",
    response_model=list[MemberAvailabilityEntry],
)
def get_group_admin_availability(
    group_id: uuid.UUID,
    start: date,
    end: date,
    auth_data: tuple[Group, GroupMembership, User] = Depends(get_authorized_membership),
    session: Session = Depends(get_request_session),
):
    group, membership, _ = auth_data
    if membership.role != MembershipRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only group owners can access group administrative availability",
        )
    if start > end:
        raise HTTPException(
            status_code=422, detail="start date must be before or equal to end date"
        )

    members_stmt = (
        select(User, GroupMembership)
        .join(GroupMembership, GroupMembership.user_id == User.id)
        .where(GroupMembership.group_id == group.id)
    )
    members = session.execute(members_stmt).all()
    user_map = {
        member.id: _effective_group_display_name(member, membership)
        for member, membership in members
    }
    if not user_map:
        return []

    avail_stmt = select(Availability).where(
        Availability.user_id.in_(user_map.keys()),
        Availability.day >= start,
        Availability.day <= end,
    )
    avail_entries = session.scalars(avail_stmt).all()
    status_map = {
        AvailabilityStatus.AVAILABLE: "Available",
        AvailabilityStatus.MAYBE: "Maybe",
        AvailabilityStatus.UNAVAILABLE: "No",
    }
    return [
        MemberAvailabilityEntry(
            group_name=group.name,
            user_name=user_map[entry.user_id],
            user_id=entry.user_id,
            date=entry.day.isoformat(),
            status=status_map[entry.status],
        )
        for entry in avail_entries
        if entry.user_id in user_map
    ]


@router.get("/test-health")
def health_check():
    return {"status": "ok"}


def create_app(
    app_settings: Settings | None = None,
    database_runtime: DatabaseRuntime | None = None,
) -> FastAPI:
    runtime_settings = app_settings or settings
    invite_join_rate_limiter = InviteJoinRateLimiter()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        runtime: DatabaseRuntime | None = None
        try:
            runtime_settings.validate_production_clerk_configuration()
            if database_runtime is None:
                runtime = create_required_database_runtime(
                    runtime_settings.database_url
                )
            else:
                runtime = database_runtime
                validate_injected_runtime(
                    runtime_settings.database_url,
                    database_runtime,
                )

            application.state.database_runtime = runtime
            validate_database_readiness(runtime)
            yield
        finally:
            if runtime is not None:
                runtime.dispose()

    logging.basicConfig(level=runtime_settings.log_level)
    # Alembic's in-process logging setup can disable loggers created earlier.
    logger.disabled = False

    application = FastAPI(lifespan=lifespan)
    application.state.settings = runtime_settings
    application.state.invite_join_rate_limiter = invite_join_rate_limiter
    application.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(router)
    return application


app = create_app()
