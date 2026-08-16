"""Phase 1 PostgreSQL compatibility API.

The five existing name-shaped routes remain temporary compatibility surfaces.
They preserve the current frontend contract and are scheduled for replacement
by scoped, ID-shaped APIs in Phase 2.
"""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import compatibility
from .auth import get_current_account, get_current_dnd_user
from .config import Settings, settings
from .db import (
    DatabaseRuntime,
    create_required_database_runtime,
    get_request_session,
    validate_database_readiness,
    validate_injected_runtime,
)
from .models import (
    Account,
    Availability,
    AvailabilityStatus,
    Group,
    GroupMembership,
    MembershipRole,
    User,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class AccountResponse(BaseModel):
    id: uuid.UUID
    email: str | None = None
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


class AvailabilityUpdate(BaseModel):
    group: str
    user: str
    date: date
    status: Literal["Available", "Maybe", "No"] | None


class GroupInfo(BaseModel):
    name: str
    players: list[str]


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


@router.get("/me", response_model=AccountResponse)
@router.get("/api/me", response_model=AccountResponse)
def get_me(account: Account = Depends(get_current_account)):
    return AccountResponse(
        id=account.id,
        email=account.email,
        display_name=account.display_name,
    )


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
            display_name=u.display_name,
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
        select(User)
        .join(GroupMembership, GroupMembership.user_id == User.id)
        .where(GroupMembership.group_id == group.id)
    )
    members = session.scalars(members_stmt).all()
    user_map = {m.id: m.display_name for m in members}
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
        select(User)
        .join(GroupMembership, GroupMembership.user_id == User.id)
        .where(GroupMembership.group_id == group.id)
    )
    members = session.scalars(members_stmt).all()
    user_map = {m.id: m.display_name for m in members}
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


@router.get("/groups", response_model=list[GroupInfo])
def get_groups(session: Session = Depends(get_request_session)):
    return compatibility.get_groups(session)


@router.get("/availability/{group}/{year}/{month}")
def get_availability(
    group: str,
    year: int,
    month: int,
    session: Session = Depends(get_request_session),
):
    try:
        return compatibility.get_group_month_availability(
            session,
            group,
            year,
            month,
        )
    except compatibility.CompatibilityInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/availability")
def update_availability(
    request: Request,
    update: AvailabilityUpdate,
    session: Session = Depends(get_request_session),
):
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503,
            detail="Availability mutations are temporarily disabled",
        )
    try:
        compatibility.set_user_availability(
            session,
            update.group,
            update.user,
            update.date,
            update.status,
        )
    except compatibility.CompatibilityInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except compatibility.CompatibilityPersistenceError:
        raise HTTPException(
            status_code=503,
            detail="Availability mutation could not be completed",
        ) from None
    return {"status": "success", "new_state": update.status}


@router.get("/admin/all-availability")
def get_all_availability(
    start: date,
    end: date,
    session: Session = Depends(get_request_session),
):
    # Temporary anonymous endpoint: remove with the compatibility API in Phase 2.
    return compatibility.get_all_availability(session, start, end)


@router.get("/test-health")
def health_check():
    return {"status": "ok"}


def create_app(
    app_settings: Settings | None = None,
    database_runtime: DatabaseRuntime | None = None,
) -> FastAPI:
    runtime_settings = app_settings or settings

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
            with runtime.open_session() as startup_session:
                compatibility.validate_compatibility_dataset(startup_session)
                startup_session.rollback()

            logger.warning(
                "phase1_compatibility_mode_active mutations_enabled=%s",
                runtime_settings.mutations_enabled,
            )
            yield
        finally:
            if runtime is not None:
                runtime.dispose()

    logging.basicConfig(level=runtime_settings.log_level)
    # Alembic's in-process logging setup can disable loggers created earlier.
    logger.disabled = False

    application = FastAPI(lifespan=lifespan)
    application.state.settings = runtime_settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(compatibility.CompatibilityDatasetError)
    async def compatibility_dataset_error(
        request: Request,
        exc: compatibility.CompatibilityDatasetError,
    ) -> JSONResponse:
        del request, exc
        return JSONResponse(
            status_code=503,
            content={"detail": "Compatibility data is temporarily unavailable"},
        )

    application.include_router(router)
    return application


app = create_app()
