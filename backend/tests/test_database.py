import sqlite3
from datetime import date
from pathlib import Path

from backend import database


def test_initialization_creates_only_current_availability_schema(
    database_path: Path,
) -> None:
    database.init_db(database_path)

    with sqlite3.connect(database_path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE ?",
            ("table", "sqlite_%"),
        ).fetchall()
        columns = connection.execute("PRAGMA table_info(availability)").fetchall()

    assert tables == [("availability",)]
    assert [(column[1], column[2], column[5]) for column in columns] == [
        ("group_name", "TEXT", 1),
        ("user_name", "TEXT", 2),
        ("date", "TEXT", 3),
        ("status", "TEXT", 0),
    ]


def test_set_replaces_and_clear_removes_current_value(database_path: Path) -> None:
    database.init_db(database_path)
    day = date(2026, 1, 5)

    database.set_user_availability(
        "Green flag", "Ulrich", day, "Available", database_path
    )
    assert (
        database.get_user_availability("Green flag", "Ulrich", day, database_path)
        == "Available"
    )

    database.set_user_availability("Green flag", "Ulrich", day, "Maybe", database_path)
    assert (
        database.get_user_availability("Green flag", "Ulrich", day, database_path)
        == "Maybe"
    )

    database.set_user_availability("Green flag", "Ulrich", day, None, database_path)
    assert (
        database.get_user_availability("Green flag", "Ulrich", day, database_path)
        is None
    )


def test_shared_user_status_propagates_and_clears_for_all_memberships(
    database_path: Path,
) -> None:
    database.init_db(database_path)
    day = date(2026, 2, 6)

    database.set_user_availability("Green flag", "Dembe", day, "No", database_path)
    assert {
        group: database.get_user_availability(group, "Dembe", day, database_path)
        for group in database.get_user_groups("Dembe")
    } == {"Green flag": "No", "1D6": "No", "Underdark": "No"}

    database.set_user_availability("1D6", "Dembe", day, None, database_path)
    assert all(
        database.get_user_availability(group, "Dembe", day, database_path) is None
        for group in database.get_user_groups("Dembe")
    )


def test_month_filtering_excludes_adjacent_months(database_path: Path) -> None:
    database.init_db(database_path)
    for day in (date(2026, 2, 28), date(2026, 3, 1), date(2026, 4, 1)):
        database.set_user_availability(
            "Green flag", "Quentin", day, "Available", database_path
        )

    rows = database.get_group_month_availability("Green flag", 2026, 3, database_path)

    assert [row["date"] for row in rows] == ["2026-03-01"]


def test_all_availability_range_is_inclusive(database_path: Path) -> None:
    database.init_db(database_path)
    for day in (
        date(2026, 4, 9),
        date(2026, 4, 10),
        date(2026, 4, 20),
        date(2026, 4, 21),
    ):
        database.set_user_availability(
            "Green flag", "Ulrich", day, "Available", database_path
        )

    rows = database.get_all_availability("2026-04-10", "2026-04-20", database_path)

    assert {row["date"] for row in rows} == {"2026-04-10", "2026-04-20"}


def test_sql_values_are_bound_as_parameters(database_path: Path) -> None:
    database.init_db(database_path)
    suspicious_user = "Robert'); DROP TABLE availability;--"
    day = date(2026, 5, 1)

    database.set_user_availability(
        "Green flag", suspicious_user, day, "Available", database_path
    )

    assert (
        database.get_user_availability(
            "Green flag", suspicious_user, day, database_path
        )
        == "Available"
    )
    with sqlite3.connect(database_path) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = ? AND name = ?",
            ("table", "availability"),
        ).fetchone()
    assert table == ("availability",)
