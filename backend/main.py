import logging
from contextlib import asynccontextmanager
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import database
from .config import Settings, settings

router = APIRouter()


# --- Pydantic Models ---
class AvailabilityUpdate(BaseModel):
    group: str
    user: str
    date: date
    status: Optional[str]


class GroupInfo(BaseModel):
    name: str
    players: List[str]


# --- Endpoints ---


@router.get("/groups", response_model=List[GroupInfo])
def get_groups():
    return [
        {"name": name, "players": players} for name, players in database.GROUPS.items()
    ]


@router.get("/availability/{group}/{year}/{month}")
def get_availability(request: Request, group: str, year: int, month: int):
    return database.get_group_month_availability(
        group,
        year,
        month,
        request.app.state.settings.database_path,
    )


@router.post("/availability")
def update_availability(request: Request, update: AvailabilityUpdate):
    database.set_user_availability(
        update.group,
        update.user,
        update.date,
        update.status,
        request.app.state.settings.database_path,
    )
    return {"status": "success", "new_state": update.status}


@router.get("/admin/all-availability")
def get_all_availability(request: Request, start: date, end: date):
    return database.get_all_availability(
        start.isoformat(),
        end.isoformat(),
        request.app.state.settings.database_path,
    )


@router.get("/test-health")
def health_check():
    return {"status": "ok"}


def create_app(app_settings: Settings | None = None) -> FastAPI:
    runtime_settings = app_settings or settings

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.init_db(runtime_settings.database_path)
        yield

    logging.basicConfig(level=runtime_settings.log_level)

    application = FastAPI(lifespan=lifespan)
    application.state.settings = runtime_settings
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
