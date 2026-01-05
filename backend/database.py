import sqlite3
import os
from typing import List, Optional, Dict
from datetime import date, timedelta
import calendar
import random

# Define base path to share DB with previous app version
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(BASE_DIR, "dnd_planner.db")

GROUPS = {
    "Green flag": ["Jiken", "Nuxio", "Ulrich", "Daerrus"],
    "Red flags": ["Gaelle", "Rico", "Yoann", "Romane", "Victor"]
}

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS availability (
            group_name TEXT,
            user_name TEXT,
            date TEXT,
            status TEXT,
            PRIMARY KEY (group_name, user_name, date)
        )
    ''')
    conn.commit()
    conn.close()

# Initialize on module load
init_db()

def get_user_availability(group: str, user: str, date_obj: date) -> Optional[str]:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT status FROM availability WHERE group_name=? AND user_name=? AND date=?", 
              (group, user, date_obj.isoformat()))
    result = c.fetchone()
    conn.close()
    return result['status'] if result else None

def set_user_availability(group: str, user: str, date_obj: date, status: Optional[str]):
    conn = get_db_connection()
    c = conn.cursor()
    if status:
        c.execute("INSERT OR REPLACE INTO availability (group_name, user_name, date, status) VALUES (?, ?, ?, ?)",
                  (group, user, date_obj.isoformat(), status))
    else:
        c.execute("DELETE FROM availability WHERE group_name=? AND user_name=? AND date=?",
                  (group, user, date_obj.isoformat()))
    conn.commit()
    conn.close()

def get_group_month_availability(group: str, year: int, month: int) -> List[Dict]:
    """Fetch all availability for a specific group in a given month."""
    start_date = date(year, month, 1)
    # Simple logic: string comparison works for ISO dates YYYY-MM-DD
    # We'll just fetch all and filter in python or exact match if needed.
    # ISO dates: 2026-01-01 to 2026-01-31
    # Pattern matching '2026-01-%'
    month_str = f"{year}-{month:02d}-%"
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM availability WHERE group_name=? AND date LIKE ?", (group, month_str))
    rows = c.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def get_all_availability(start_date: str, end_date: str) -> List[Dict]:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM availability WHERE date >= ? AND date <= ?", (start_date, end_date))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def generate_test_data(year: int, month: int):
    """Generates random data for a specific month for all players."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Clear existing data for that month to avoid dupes/mess
    start_date = date(year, month, 1)
    # pattern matching for deletion
    month_str = f"{year}-{month:02d}-%"
    c.execute("DELETE FROM availability WHERE date LIKE ?", (month_str,))
    
    num_days = calendar.monthrange(year, month)[1]
    
    # Include Admin in test data generation
    target_groups = {**GROUPS, "Admin": ["Admin"]}

    for group_name, players in target_groups.items():
        for player in players:
            for day in range(1, num_days + 1):
                r = random.random()
                status = 'No'
                if r < 0.4: status = 'Available'
                elif r < 0.6: status = 'Maybe'
                
                date_str = date(year, month, day).isoformat()
                c.execute("INSERT INTO availability (group_name, user_name, date, status) VALUES (?, ?, ?, ?)",
                          (group_name, player, date_str, status))
    conn.commit()
    conn.close()
