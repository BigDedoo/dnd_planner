from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import date
from . import database
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Allow CORS for Next.js dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.get("/groups", response_model=List[GroupInfo])
def get_groups():
    return [{"name": name, "players": players} for name, players in database.GROUPS.items()]

@app.get("/availability/{group}/{year}/{month}")
def get_availability(group: str, year: int, month: int):
    return database.get_group_month_availability(group, year, month)

@app.post("/availability")
def update_availability(update: AvailabilityUpdate):
    database.set_user_availability(update.group, update.user, update.date, update.status)
    return {"status": "success", "new_state": update.status}

@app.get("/admin/all-availability")
def get_all_availability(start: date, end: date):
    return database.get_all_availability(start.isoformat(), end.isoformat())

@app.get("/test-health")
def health_check():
    return {"status": "ok", "db": database.DB_FILE}
