"""Synthetic, authenticated regression coverage for group availability modes."""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.auth import resolve_or_provision_account
from backend.availability import set_availability_mode
from backend.config import Settings
from backend.db import DatabaseRuntime
from backend.main import create_app
from backend.models import (
    Availability,
    AvailabilityMode,
    AvailabilityStatus,
    Base,
    Group,
    GroupAvailability,
    GroupMembership,
    MembershipRole,
    User,
)
from backend.tests.test_phase_2b_auth import MockRequestAuthenticator


@pytest.fixture
def setup(tmp_path: Path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'modes.db'}")

    @sa.event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.create_function(
            "btrim", 1, lambda value: value.strip() if value else value
        )
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    runtime = DatabaseRuntime(engine=engine, safe_url="synthetic local test database")
    auth = MockRequestAuthenticator()
    ids = {
        name: uuid.uuid4() for name in ("alice", "bob", "carol", "outsider", "a", "b")
    }
    with Session(engine) as session:
        users = {}
        for name in ("alice", "bob", "carol", "outsider"):
            auth.add_session(
                token=name, subject=f"availability-{name}", display_name=name
            )
            account = resolve_or_provision_account(
                session, "clerk", f"availability-{name}"
            )
            users[name] = User(id=ids[name], account_id=account.id, display_name=name)
        session.add_all(
            [
                *users.values(),
                Group(id=ids["a"], name="Green Flag"),
                Group(id=ids["b"], name="Underdark"),
            ]
        )
        session.flush()
        session.add_all(
            [
                GroupMembership(
                    group_id=ids["a"],
                    user_id=ids["alice"],
                    role=MembershipRole.OWNER,
                    display_order=0,
                ),
                GroupMembership(
                    group_id=ids["a"],
                    user_id=ids["bob"],
                    role=MembershipRole.MEMBER,
                    display_order=1,
                ),
                GroupMembership(
                    group_id=ids["a"],
                    user_id=ids["carol"],
                    role=MembershipRole.MEMBER,
                    display_order=2,
                ),
                GroupMembership(
                    group_id=ids["b"],
                    user_id=ids["bob"],
                    role=MembershipRole.OWNER,
                    display_order=0,
                ),
                GroupMembership(
                    group_id=ids["b"],
                    user_id=ids["alice"],
                    role=MembershipRole.MEMBER,
                    display_order=1,
                ),
                Availability(
                    user_id=ids["alice"],
                    day=date(2026, 10, 11),
                    status=AvailabilityStatus.MAYBE,
                ),
                Availability(
                    user_id=ids["alice"],
                    day=date(2026, 10, 12),
                    status=AvailabilityStatus.AVAILABLE,
                ),
                Availability(
                    user_id=ids["bob"],
                    day=date(2026, 10, 12),
                    status=AvailabilityStatus.AVAILABLE,
                ),
            ]
        )
        session.commit()
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        LOG_LEVEL="CRITICAL",
        CORS_ALLOWED_ORIGINS=["http://testserver"],
    )
    app = create_app(settings, database_runtime=runtime)
    with patch("backend.main.validate_database_readiness"), TestClient(app) as client:
        app.state.request_authenticator = auth
        app.state.clerk_profile_client = auth
        yield client, engine, ids
    runtime.dispose()


def headers(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {name}"}


def mode(client: TestClient, group_id: uuid.UUID, name: str, value: str):
    return client.patch(
        f"/api/groups/{group_id}/me/availability-mode",
        headers=headers(name),
        json={"availability_mode": value},
    )


def update(client: TestClient, group_id: uuid.UUID, name: str, value: str | None):
    return client.post(
        f"/api/groups/{group_id}/availability",
        headers=headers(name),
        json={"date": "2026-10-12", "status": value},
    )


def statuses(client: TestClient, group_id: uuid.UUID, name: str) -> dict[str, str]:
    response = client.get(
        f"/api/groups/{group_id}/availability/2026/10", headers=headers(name)
    )
    assert response.status_code == 200
    assert all(row["group_id"] == str(group_id) for row in response.json())
    return {
        row["user_id"]: row["status"]
        for row in response.json()
        if row["date"] == "2026-10-12"
    }


def test_snapshot_is_once_and_effective_reads_never_fall_back(setup):
    client, engine, ids = setup
    a, b = ids["a"], ids["b"]
    with Session(engine) as session:
        membership = session.get(GroupMembership, (b, ids["alice"]))
        assert membership.availability_mode == AvailabilityMode.GLOBAL
        assert membership.separate_availability_initialized is False
        assert (
            session.scalar(sa.select(sa.func.count()).select_from(GroupAvailability))
            == 0
        )
    assert statuses(client, a, "alice")[str(ids["alice"])] == "Available"
    assert mode(client, b, "alice", "separate").json() == {
        "availability_mode": "separate"
    }
    with Session(engine) as session:
        membership = session.get(GroupMembership, (b, ids["alice"]))
        assert membership.separate_availability_initialized is True
        rows = session.scalars(
            sa.select(GroupAvailability).where(GroupAvailability.group_id == b)
        ).all()
        assert {(row.day, row.status) for row in rows} == {
            (date(2026, 10, 11), AvailabilityStatus.MAYBE),
            (date(2026, 10, 12), AvailabilityStatus.AVAILABLE),
        }
        assert (
            session.get(Availability, (ids["alice"], date(2026, 10, 12))).status
            == AvailabilityStatus.AVAILABLE
        )
    assert update(client, b, "alice", "No").status_code == 200
    assert statuses(client, b, "alice")[str(ids["alice"])] == "No"
    assert statuses(client, a, "alice")[str(ids["alice"])] == "Available"
    assert mode(client, a, "bob", "separate").status_code == 200
    assert update(client, a, "bob", "No").status_code == 200
    assert mode(client, a, "carol", "separate").status_code == 200
    expected = {str(ids["alice"]): "Available", str(ids["bob"]): "No"}
    assert statuses(client, a, "alice") == expected
    admin = client.get(
        f"/api/groups/{a}/admin/availability?start=2026-10-12&end=2026-10-12",
        headers=headers("alice"),
    )
    assert {row["user_id"]: row["status"] for row in admin.json()} == expected
    assert all(row["group_id"] == str(a) for row in admin.json())
    assert update(client, b, "alice", None).status_code == 200
    assert str(ids["alice"]) not in statuses(client, b, "alice")
    assert mode(client, b, "alice", "global").status_code == 200
    assert statuses(client, b, "alice")[str(ids["alice"])] == "Available"
    assert update(client, a, "alice", "Maybe").status_code == 200
    assert statuses(client, a, "alice")[str(ids["alice"])] == "Maybe"
    assert statuses(client, b, "alice")[str(ids["alice"])] == "Maybe"
    assert mode(client, b, "alice", "separate").status_code == 200
    assert str(ids["alice"]) not in statuses(client, b, "alice")
    assert update(client, b, "alice", "No").status_code == 200
    assert mode(client, b, "alice", "global").status_code == 200
    assert mode(client, b, "alice", "separate").status_code == 200
    assert statuses(client, b, "alice")[str(ids["alice"])] == "No"
    assert mode(client, b, "alice", "separate").status_code == 200
    with Session(engine) as session:
        assert (
            session.get(Availability, (ids["alice"], date(2026, 10, 12))).status
            == AvailabilityStatus.MAYBE
        )
        assert (
            session.scalar(
                sa.select(sa.func.count())
                .select_from(GroupAvailability)
                .where(GroupAvailability.group_id == b)
            )
            == 2
        )


def test_permissions_and_membership_cleanup(setup):
    client, engine, ids = setup
    a, b = ids["a"], ids["b"]
    assert mode(client, a, "outsider", "separate").status_code == 403
    assert mode(client, a, "bob", "separate").status_code == 200
    with Session(engine) as session:
        assert (
            session.get(GroupMembership, (a, ids["alice"])).availability_mode
            == AvailabilityMode.GLOBAL
        )
        assert (
            session.get(GroupMembership, (a, ids["bob"])).availability_mode
            == AvailabilityMode.SEPARATE
        )
    assert update(client, a, "bob", "No").status_code == 200
    removal = client.delete(
        f"/api/groups/{a}/members/{ids['bob']}", headers=headers("alice")
    )
    assert removal.status_code == 200
    with Session(engine) as session:
        assert (
            session.get(GroupAvailability, (a, ids["bob"], date(2026, 10, 12))) is None
        )
        assert session.get(Availability, (ids["bob"], date(2026, 10, 12))) is not None
    assert mode(client, b, "alice", "separate").status_code == 200
    leaving = client.post(f"/api/groups/{b}/leave", headers=headers("alice"))
    assert leaving.status_code == 200
    with Session(engine) as session:
        assert (
            session.get(GroupAvailability, (b, ids["alice"], date(2026, 10, 12)))
            is None
        )
        assert session.get(Availability, (ids["alice"], date(2026, 10, 12))) is not None


def test_initialization_failure_rolls_back_mode_and_snapshot(setup):
    _, engine, ids = setup
    session = Session(engine)

    def fail_snapshot(_session, _context, _instances):
        if any(isinstance(row, GroupAvailability) for row in _session.new):
            raise RuntimeError("synthetic snapshot failure")

    sa.event.listen(session, "before_flush", fail_snapshot)
    try:
        with pytest.raises(RuntimeError, match="synthetic snapshot failure"):
            with session.begin():
                membership = session.scalar(
                    sa.select(GroupMembership)
                    .where(
                        GroupMembership.group_id == ids["b"],
                        GroupMembership.user_id == ids["alice"],
                    )
                    .with_for_update()
                )
                set_availability_mode(session, membership, AvailabilityMode.SEPARATE)
    finally:
        session.close()
    with Session(engine) as verify:
        membership = verify.get(GroupMembership, (ids["b"], ids["alice"]))
        assert membership.availability_mode == AvailabilityMode.GLOBAL
        assert membership.separate_availability_initialized is False
        assert (
            verify.scalar(sa.select(sa.func.count()).select_from(GroupAvailability))
            == 0
        )


def test_clearing_all_separate_rows_does_not_reinitialize(setup):
    client, engine, ids = setup
    group_id = ids["b"]
    assert mode(client, group_id, "alice", "separate").status_code == 200
    assert update(client, group_id, "alice", None).status_code == 200
    assert (
        client.post(
            f"/api/groups/{group_id}/availability",
            headers=headers("alice"),
            json={"date": "2026-10-11", "status": None},
        ).status_code
        == 200
    )
    with Session(engine) as session:
        assert (
            session.scalar(sa.select(sa.func.count()).select_from(GroupAvailability))
            == 0
        )
    assert mode(client, group_id, "alice", "global").status_code == 200
    assert mode(client, group_id, "alice", "separate").status_code == 200
    assert str(ids["alice"]) not in statuses(client, group_id, "alice")
    with Session(engine) as session:
        assert (
            session.scalar(sa.select(sa.func.count()).select_from(GroupAvailability))
            == 0
        )


def test_group_deletion_cleans_separate_rows_but_not_global(setup):
    client, engine, ids = setup
    group_id = ids["b"]
    assert mode(client, group_id, "alice", "separate").status_code == 200
    response = client.delete(f"/api/groups/{group_id}", headers=headers("bob"))
    assert response.status_code == 204
    with Session(engine) as session:
        assert (
            session.scalar(sa.select(sa.func.count()).select_from(GroupAvailability))
            == 0
        )
        assert session.get(Availability, (ids["alice"], date(2026, 10, 12))) is not None


def test_new_invite_membership_defaults_global_and_mode_respects_mutation_guard(setup):
    client, engine, ids = setup
    group_id = ids["a"]
    created = client.post(f"/api/groups/{group_id}/invite", headers=headers("alice"))
    assert created.status_code == 200
    joined = client.post(
        "/api/groups/join",
        headers=headers("outsider"),
        json={"code": created.json()["code"]},
    )
    assert joined.status_code == 200
    with Session(engine) as session:
        membership = session.get(GroupMembership, (group_id, ids["outsider"]))
        assert membership.availability_mode == AvailabilityMode.GLOBAL
        assert membership.separate_availability_initialized is False
    client.app.state.settings.mutations_enabled = False
    assert mode(client, group_id, "outsider", "separate").status_code == 503
    assert update(client, group_id, "outsider", "Available").status_code == 503
