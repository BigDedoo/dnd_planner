from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from backend import database


def post_availability(
    client: TestClient,
    *,
    group: str,
    user: str,
    date: str,
    status: str | None,
):
    return client.post(
        "/availability",
        json={"group": group, "user": user, "date": date, "status": status},
    )


def test_month_read_filters_dates_members_and_duplicates(
    legacy_client: TestClient,
    database_path: Path,
) -> None:
    database.set_user_availability(
        "Green flag", "Quentin", date(2026, 1, 10), "Available", database_path
    )
    database.set_user_availability(
        "Green flag", "Arnaud", date(2026, 2, 1), "Maybe", database_path
    )
    database.set_user_availability(
        "1D6", "Rico", date(2026, 1, 12), "No", database_path
    )
    database.set_user_availability(
        "Green flag", "Dembe", date(2026, 1, 15), "Maybe", database_path
    )

    response = legacy_client.get("/availability/Green flag/2026/1")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert {
        (row["group_name"], row["user_name"], row["date"], row["status"])
        for row in rows
    } == {
        ("Green flag", "Quentin", "2026-01-10", "Available"),
        ("Green flag", "Dembe", "2026-01-15", "Maybe"),
    }
    assert all(
        set(row) == {"group_name", "user_name", "date", "status"} for row in rows
    )


def test_empty_month_and_unknown_group_return_current_empty_response(
    legacy_client: TestClient,
) -> None:
    assert legacy_client.get("/availability/Green flag/2026/3").json() == []
    unknown_response = legacy_client.get("/availability/Unknown/2026/3")
    assert unknown_response.status_code == 200
    assert unknown_response.json() == []


def test_shared_user_is_visible_once_in_each_current_group(
    legacy_client: TestClient,
) -> None:
    write_response = post_availability(
        legacy_client,
        group="Green flag",
        user="Dembe",
        date="2026-04-04",
        status="Available",
    )
    assert write_response.status_code == 200

    for group in ("Green flag", "1D6", "Underdark"):
        rows = legacy_client.get(f"/availability/{group}/2026/4").json()
        assert rows == [
            {
                "group_name": group,
                "user_name": "Dembe",
                "date": "2026-04-04",
                "status": "Available",
            }
        ]


def test_canonical_frontend_status_sequence_is_stored_replaced_and_cleared(
    legacy_client: TestClient,
) -> None:
    endpoint = "/availability/Green flag/2026/5"

    for status in ("Available", "Maybe", "No"):
        response = post_availability(
            legacy_client,
            group="Green flag",
            user="Ulrich",
            date="2026-05-09",
            status=status,
        )
        assert response.status_code == 200
        assert response.json() == {"status": "success", "new_state": status}
        assert legacy_client.get(endpoint).json() == [
            {
                "group_name": "Green flag",
                "user_name": "Ulrich",
                "date": "2026-05-09",
                "status": status,
            }
        ]

    clear_response = post_availability(
        legacy_client,
        group="Green flag",
        user="Ulrich",
        date="2026-05-09",
        status=None,
    )
    assert clear_response.status_code == 200
    assert clear_response.json() == {"status": "success", "new_state": None}
    assert legacy_client.get(endpoint).json() == []


def test_shared_user_update_and_clear_apply_globally(
    legacy_client: TestClient,
) -> None:
    for status in ("Available", "No"):
        response = post_availability(
            legacy_client,
            group="1D6",
            user="Dembe",
            date="2026-06-14",
            status=status,
        )
        assert response.status_code == 200
        for group in ("Green flag", "1D6", "Underdark"):
            rows = legacy_client.get(f"/availability/{group}/2026/6").json()
            assert len(rows) == 1
            assert rows[0]["group_name"] == group
            assert rows[0]["status"] == status

    post_availability(
        legacy_client,
        group="Underdark",
        user="Dembe",
        date="2026-06-14",
        status=None,
    )
    for group in ("Green flag", "1D6", "Underdark"):
        assert legacy_client.get(f"/availability/{group}/2026/6").json() == []


def test_malformed_date_uses_fastapi_validation_response(
    legacy_client: TestClient,
) -> None:
    response = post_availability(
        legacy_client,
        group="Green flag",
        user="Quentin",
        date="not-a-date",
        status="Available",
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert len(detail) == 1
    assert detail[0]["loc"] == ["body", "date"]
    assert detail[0]["type"] == "date_from_datetime_parsing"
    assert detail[0]["input"] == "not-a-date"


def test_legacy_oracle_documents_noncanonical_status_acceptance(
    legacy_client: TestClient,
) -> None:
    response = post_availability(
        legacy_client,
        group="Green flag",
        user="Quentin",
        date="2026-07-01",
        status="definitely-not-valid",
    )

    assert response.status_code == 200
    assert response.json()["new_state"] == "definitely-not-valid"


def test_temporary_admin_read_is_inclusive_and_expands_global_availability(
    legacy_client: TestClient,
    database_path: Path,
) -> None:
    # Temporary legacy endpoint: remove when scoped /v1 routes and authorization land.
    database.set_user_availability(
        "Green flag", "Dembe", date(2026, 8, 10), "Available", database_path
    )
    database.set_user_availability(
        "Green flag", "Quentin", date(2026, 8, 20), "Maybe", database_path
    )
    database.set_user_availability(
        "Green flag", "Ulrich", date(2026, 8, 21), "No", database_path
    )

    response = legacy_client.get(
        "/admin/all-availability?start=2026-08-10&end=2026-08-20"
    )

    assert response.status_code == 200
    rows = response.json()
    assert {(row["user_name"], row["date"]) for row in rows} == {
        ("Dembe", "2026-08-10"),
        ("Quentin", "2026-08-20"),
    }
    assert {row["group_name"] for row in rows if row["user_name"] == "Dembe"} == {
        "Green flag",
        "1D6",
        "Underdark",
    }
    assert {row["group_name"] for row in rows if row["user_name"] == "Quentin"} == {
        "Green flag",
        "Underdark",
    }
    assert all(row["date"] != "2026-08-21" for row in rows)
