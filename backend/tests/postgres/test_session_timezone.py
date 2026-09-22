"""Synthetic PostgreSQL API checks; no real accounts or production data."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.auth import get_current_dnd_user
from backend.config import Settings
from backend.db import create_database_runtime
from backend.main import create_app
from backend.models import (
    Availability,
    AvailabilityStatus,
    Group,
    GroupMembership,
    MembershipRole,
    User,
)


@pytest.fixture
def api(postgres_database_url, db_session):
    users = {
        role: User(display_name=role)
        for role in ("owner", "organizer", "member", "outsider")
    }
    group = Group(name="Synthetic campaign", timezone="UTC")
    other = Group(name="Unchanged campaign", timezone="UTC")
    db_session.add_all([*users.values(), group, other])
    db_session.flush()
    db_session.add_all(
        [
            GroupMembership(
                group_id=group.id,
                user_id=user.id,
                role=MembershipRole(role),
                display_order=index,
            )
            for index, (role, user) in enumerate(users.items())
            if role != "outsider"
        ]
    )
    db_session.add(
        GroupMembership(
            group_id=other.id,
            user_id=users["outsider"].id,
            role=MembershipRole.OWNER,
            display_order=0,
        )
    )
    db_session.add(
        Availability(
            user_id=users["owner"].id,
            day=date(2026, 8, 29),
            status=AvailabilityStatus.AVAILABLE,
        )
    )
    db_session.commit()
    current = {"user": users["owner"]}
    runtime = create_database_runtime(postgres_database_url)
    app = create_app(
        Settings(
            _env_file=None,
            APP_ENV="test",
            LOG_LEVEL="CRITICAL",
            DATABASE_URL=postgres_database_url,
            MUTATIONS_ENABLED=True,
        ),
        runtime,
    )
    app.dependency_overrides[get_current_dnd_user] = lambda: current["user"]
    with TestClient(app) as client:
        yield client, group, other, users, current


def test_new_group_defaults_and_existing_rows_unchanged(api, db_session):
    client, group, other, _, _ = api
    created = client.post("/api/groups", json={"name": "Paris default"})
    assert created.status_code == 201
    assert created.json()["timezone"] == "Europe/Paris"
    explicit = client.post(
        "/api/groups", json={"name": "London", "timezone": "Europe/London"}
    )
    assert explicit.status_code == 201
    assert explicit.json()["timezone"] == "Europe/London"
    for zone in ("Not/AZone", " "):
        assert (
            client.post(
                "/api/groups", json={"name": "Invalid", "timezone": zone}
            ).status_code
            == 422
        )
    db_session.expire_all()
    assert db_session.get(Group, group.id).timezone == "UTC"
    assert db_session.get(Group, other.id).timezone == "UTC"


@pytest.mark.parametrize("role", ["member", "organizer", "outsider"])
def test_non_owner_cannot_change_timezone(api, role):
    client, group, _, users, current = api
    current["user"] = users[role]
    assert (
        client.patch(
            f"/api/groups/{group.id}", json={"timezone": "Europe/Paris"}
        ).status_code
        == 403
    )


def test_partial_settings_and_clear_validation(api):
    client, group, _, _, _ = api
    path = f"/api/groups/{group.id}"
    assert client.patch(path, json={"name": " Renamed "}).json()["name"] == "Renamed"
    result = client.patch(path, json={"timezone": "Europe/Paris"})
    assert result.status_code == 200
    assert result.json()["name"] == "Renamed"
    assert result.json()["timezone"] == "Europe/Paris"
    both = client.patch(path, json={"name": "Both", "timezone": "UTC"})
    assert both.json()["name"] == "Both"
    assert both.json()["timezone"] == "UTC"
    for payload in (
        {},
        {"extra": "ignored"},
        {"name": " "},
        {"name": None},
        {"timezone": " "},
        {"timezone": "Not/AZone"},
        {"timezone": None},
    ):
        assert client.patch(path, json=payload).status_code == 422
    assert client.get(path).json()["timezone"] == "UTC"


def test_paris_api_and_both_exports_preserve_wall_time_and_availability(
    api, db_session
):
    client, group, other, users, current = api
    path = f"/api/groups/{group.id}"
    assert client.patch(path, json={"timezone": "Europe/Paris"}).status_code == 200
    session_path = f"{path}/confirmed-sessions/2026-08-29"
    created = client.put(
        session_path,
        json={
            "title": "Dragon hunt",
            "start_time": "20:00",
            "duration_minutes": 180,
            "notes": "Bring dice, snacks",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["start_time"] == "20:00:00"
    assert payload["starts_at_utc"] == "2026-08-29T18:00:00Z"
    assert payload["ends_at_utc"] == "2026-08-29T21:00:00Z"
    assert payload["group_timezone"] == "Europe/Paris"
    # A second group has a different zone, but the same local session time.
    current["user"] = users["outsider"]
    assert (
        client.put(
            f"/api/groups/{other.id}/confirmed-sessions/2026-08-29",
            json={"start_time": "20:00", "duration_minutes": 180},
        ).status_code
        == 200
    )
    current["user"] = users["owner"]
    personal = client.get(
        "/api/me/confirmed-sessions?start=2026-08-01&end=2026-08-31"
    ).json()
    assert len(personal) == 1  # unrelated group remains private
    assert personal[0]["starts_at_utc"] == payload["starts_at_utc"]
    for url in (
        f"{session_path}/calendar.ics",
        "/api/me/confirmed-sessions.ics?start=2026-08-01&end=2026-08-31",
    ):
        response = client.get(url)
        assert response.status_code == 200
        assert "DTSTART:20260829T180000Z" in response.text
        assert "DTEND:20260829T210000Z" in response.text
        assert "TZID" not in response.text
        assert f"UID:{payload['id']}@dnd-planner" in response.text
        assert "SUMMARY:Dragon hunt" in response.text
        assert "DESCRIPTION:Bring dice\\, snacks" in response.text
    # Editing the zone reinterprets, but never rewrites, the stored wall time.
    assert client.patch(path, json={"timezone": "UTC"}).status_code == 200
    after = client.get(
        f"{path}/confirmed-sessions?start=2026-08-01&end=2026-08-31"
    ).json()[0]
    assert after["day"] == payload["day"]
    assert after["start_time"] == payload["start_time"]
    assert after["duration_minutes"] == 180
    assert after["starts_at_utc"] == "2026-08-29T20:00:00Z"
    db_session.expire_all()
    availability = db_session.scalars(select(Availability)).all()
    assert [(row.day, row.status) for row in availability] == [
        (date(2026, 8, 29), AvailabilityStatus.AVAILABLE)
    ]


@pytest.mark.parametrize(
    "day,problem", [("2026-03-29", "nonexistent"), ("2026-10-25", "ambiguous")]
)
def test_dst_rejected_on_create_edit_and_timezone_change(api, day, problem):
    client, group, _, _, _ = api
    group_path = f"/api/groups/{group.id}"
    path = f"{group_path}/confirmed-sessions/{day}"
    details = {"start_time": "02:30", "duration_minutes": 180}
    assert client.put(path, json=details).status_code == 200  # UTC is valid
    blocked = client.patch(
        group_path, json={"name": "Must not save", "timezone": "Europe/Paris"}
    )
    assert blocked.status_code == 422
    assert problem in blocked.json()["detail"]
    assert client.get(group_path).json()["timezone"] == "UTC"
    assert client.get(group_path).json()["name"] == "Synthetic campaign"
    # Clear the timed fields, change zone, then exercise both write paths.
    assert (
        client.patch(
            path, json={"start_time": None, "duration_minutes": None}
        ).status_code
        == 200
    )
    assert (
        client.patch(group_path, json={"timezone": "Europe/Paris"}).status_code == 200
    )
    invalid_edit = client.patch(path, json=details)
    assert invalid_edit.status_code == 422
    assert problem in invalid_edit.json()["detail"]
    assert client.delete(path).status_code in (200, 204)
    invalid_reconfirm = client.put(path, json=details)
    assert invalid_reconfirm.status_code == 422
    fresh = client.post("/api/groups", json={"name": "Fresh Paris"}).json()
    invalid_create = client.put(
        f"/api/groups/{fresh['id']}/confirmed-sessions/{day}", json=details
    )
    assert invalid_create.status_code == 422
    assert problem in invalid_create.json()["detail"]


def test_all_day_and_cross_group_timezone_context(api, db_session):
    client, group, other, users, current = api
    db_session.add(
        GroupMembership(
            group_id=other.id,
            user_id=users["owner"].id,
            role=MembershipRole.MEMBER,
            display_order=1,
        )
    )
    db_session.commit()
    assert (
        client.patch(
            f"/api/groups/{group.id}", json={"timezone": "Europe/Paris"}
        ).status_code
        == 200
    )
    all_day = client.put(f"/api/groups/{group.id}/confirmed-sessions/2026-03-29").json()
    assert all_day["starts_at_utc"] is None and all_day["ends_at_utc"] is None
    response = client.get(
        "/api/me/confirmed-sessions.ics?start=2026-03-01&end=2026-03-31"
    )
    assert "DTSTART;VALUE=DATE:20260329" in response.text
    assert "DTEND;VALUE=DATE:20260330" in response.text
    single = client.get(
        f"/api/groups/{group.id}/confirmed-sessions/2026-03-29/calendar.ics"
    )
    assert "DTSTART;VALUE=DATE:20260329" in single.text
    details = {"start_time": "20:00", "duration_minutes": 180}
    assert (
        client.put(
            f"/api/groups/{group.id}/confirmed-sessions/2026-08-29", json=details
        ).status_code
        == 200
    )
    current["user"] = users["outsider"]
    assert (
        client.put(
            f"/api/groups/{other.id}/confirmed-sessions/2026-08-29", json=details
        ).status_code
        == 200
    )
    current["user"] = users["owner"]
    rows = client.get(
        "/api/me/confirmed-sessions?start=2026-08-01&end=2026-08-31"
    ).json()
    assert {row["group_timezone"]: row["starts_at_utc"] for row in rows} == {
        "Europe/Paris": "2026-08-29T18:00:00Z",
        "UTC": "2026-08-29T20:00:00Z",
    }
    personal = client.get(
        "/api/me/confirmed-sessions.ics?start=2026-08-01&end=2026-08-31"
    )
    assert personal.text.count("BEGIN:VEVENT") == 2
    assert "DTSTART:20260829T180000Z" in personal.text
    assert "DTSTART:20260829T200000Z" in personal.text
