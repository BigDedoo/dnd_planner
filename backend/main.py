"""Phase 1 PostgreSQL compatibility API.

The five existing name-shaped routes remain temporary compatibility surfaces.
They preserve the current frontend contract and are scheduled for replacement
by scoped, ID-shaped APIs in Phase 2.
"""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import compatibility
from .auth import get_current_account
from .config import Settings, settings
from .db import (
    DatabaseRuntime,
    create_required_database_runtime,
    get_request_session,
    validate_database_readiness,
    validate_injected_runtime,
)
from .models import Account

logger = logging.getLogger(__name__)
router = APIRouter()


class AccountResponse(BaseModel):
    id: uuid.UUID
    email: str | None = None
    display_name: str | None = None


class AvailabilityUpdate(BaseModel):
    group: str
    user: str
    date: date
    status: Literal["Available", "Maybe", "No"] | None


class GroupInfo(BaseModel):
    name: str
    players: list[str]


@router.get("/me", response_model=AccountResponse)
@router.get("/api/me", response_model=AccountResponse)
def get_me(account: Account = Depends(get_current_account)):
    return AccountResponse(
        id=account.id,
        email=account.email,
        display_name=account.display_name,
    )


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
