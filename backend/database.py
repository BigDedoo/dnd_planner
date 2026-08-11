import sqlite3
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import settings
from .legacy_contract import GROUPS

# Keep the configured SQLite path available to the existing database functions.
DB_FILE = str(settings.database_path)

DatabasePath = str | Path


def get_db_connection(database_path: DatabasePath | None = None):
    path = database_path if database_path is not None else DB_FILE
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(database_path: DatabasePath | None = None):
    conn = get_db_connection(database_path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS availability (
            group_name TEXT,
            user_name TEXT,
            date TEXT,
            status TEXT,
            PRIMARY KEY (group_name, user_name, date)
        )
    """)
    conn.commit()
    conn.close()


def get_user_availability(
    group: str,
    user: str,
    date_obj: date,
    database_path: DatabasePath | None = None,
) -> Optional[str]:
    conn = get_db_connection(database_path)
    c = conn.cursor()
    c.execute(
        "SELECT status FROM availability WHERE group_name=? AND user_name=? AND date=?",
        (group, user, date_obj.isoformat()),
    )
    result = c.fetchone()
    conn.close()
    return result["status"] if result else None


def get_user_groups(user: str) -> List[str]:
    return [group_name for group_name, players in GROUPS.items() if user in players]


def expand_availability_rows(rows: List[sqlite3.Row]) -> List[Dict]:
    expanded: Dict[Tuple[str, str, str], Dict] = {}

    for row in rows:
        row_dict = dict(row)
        user = row_dict["user_name"]
        target_groups = get_user_groups(user) or [row_dict["group_name"]]

        for group_name in target_groups:
            if user not in GROUPS.get(group_name, []):
                continue

            key = (group_name, user, row_dict["date"])
            expanded_row = {
                **row_dict,
                "group_name": group_name,
            }

            if key not in expanded or row_dict["group_name"] == group_name:
                expanded[key] = expanded_row

    return list(expanded.values())


def set_user_availability(
    group: str,
    user: str,
    date_obj: date,
    status: Optional[str],
    database_path: DatabasePath | None = None,
):
    conn = get_db_connection(database_path)
    c = conn.cursor()
    target_groups = list(dict.fromkeys([group, *get_user_groups(user)]))

    if status:
        c.executemany(
            "INSERT OR REPLACE INTO availability (group_name, user_name, date, status) VALUES (?, ?, ?, ?)",
            [
                (target_group, user, date_obj.isoformat(), status)
                for target_group in target_groups
            ],
        )
    else:
        c.executemany(
            "DELETE FROM availability WHERE group_name=? AND user_name=? AND date=?",
            [
                (target_group, user, date_obj.isoformat())
                for target_group in target_groups
            ],
        )
    conn.commit()
    conn.close()


def get_group_month_availability(
    group: str,
    year: int,
    month: int,
    database_path: DatabasePath | None = None,
) -> List[Dict]:
    """Fetch all availability for a specific group in a given month."""
    # Preserve the current validation behavior for invalid year/month path values.
    date(year, month, 1)
    # Simple logic: string comparison works for ISO dates YYYY-MM-DD
    # We'll just fetch all and filter in python or exact match if needed.
    # ISO dates: 2026-01-01 to 2026-01-31
    # Pattern matching '2026-01-%'
    month_str = f"{year}-{month:02d}-%"

    conn = get_db_connection(database_path)
    c = conn.cursor()
    group_players = GROUPS.get(group, [])

    if not group_players:
        conn.close()
        return []

    c.execute(
        f"SELECT * FROM availability WHERE user_name IN ({','.join(['?'] * len(group_players))}) AND date LIKE ?",
        [*group_players, month_str],
    )
    rows = c.fetchall()
    conn.close()

    return [row for row in expand_availability_rows(rows) if row["group_name"] == group]


def get_all_availability(
    start_date: str,
    end_date: str,
    database_path: DatabasePath | None = None,
) -> List[Dict]:
    conn = get_db_connection(database_path)
    c = conn.cursor()
    c.execute(
        "SELECT * FROM availability WHERE date >= ? AND date <= ?",
        (start_date, end_date),
    )
    rows = c.fetchall()
    conn.close()
    return expand_availability_rows(rows)
