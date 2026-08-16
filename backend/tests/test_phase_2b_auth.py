from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from backend.auth import (
    ClerkAuthenticationError,
    VerifiedClerkSession,
    resolve_or_provision_account,
)
from backend.clerk_profile import ClerkProfile
from backend.config import Settings
from backend.db import DatabaseRuntime
from backend.link_account import LinkAccountError, link_account_to_user
from backend.main import create_app
from backend.models import (
    Account,
    Availability,
    AvailabilityStatus,
    Base,
    ConfirmedSession,
    Group,
    GroupMembership,
    MembershipRole,
    User,
)


class MockRequestAuthenticator:
    def __init__(self) -> None:
        self.valid_sessions: dict[str, VerifiedClerkSession] = {}
        self.profiles: dict[str, ClerkProfile] = {}

    def add_session(
        self,
        token: str,
        subject: str,
        email: str | None = None,
        username: str | None = None,
        display_name: str | None = None,
    ) -> None:
        self.valid_sessions[token] = VerifiedClerkSession(subject=subject)
        self.profiles[subject] = ClerkProfile(
            email=email,
            username=username,
            display_name=display_name,
        )

    def fetch_profile(self, clerk_user_id: str) -> ClerkProfile:
        return self.profiles[clerk_user_id]

    def authenticate(
        self,
        request: Request,
        app_settings: Settings,
    ) -> VerifiedClerkSession:
        del app_settings
        token = request.headers["Authorization"].split()[1]
        try:
            return self.valid_sessions[token]
        except KeyError as exc:
            raise ClerkAuthenticationError("request_rejected") from exc


@pytest.fixture
def mock_authenticator() -> MockRequestAuthenticator:
    return MockRequestAuthenticator()


@pytest.fixture
def phase2b_sqlite_runtime(tmp_path: Path) -> Iterator[DatabaseRuntime]:
    db_file = tmp_path / "phase2b_test.db"
    engine = create_engine(f"sqlite:///{db_file}")

    @sa.event.listens_for(engine, "connect")
    def _register_sqlite_functions(dbapi_connection, _):
        dbapi_connection.create_function(
            "btrim", 1, lambda s: s.strip() if s is not None else None
        )

    Base.metadata.create_all(engine)
    runtime = DatabaseRuntime(engine=engine, safe_url=f"sqlite:///{db_file}")
    yield runtime
    runtime.dispose()


@pytest.fixture
def phase2b_app(
    phase2b_sqlite_runtime: DatabaseRuntime,
    mock_authenticator: MockRequestAuthenticator,
) -> FastAPI:
    test_settings = Settings(
        _env_file=None,
        APP_ENV="test",
        LOG_LEVEL="CRITICAL",
        CORS_ALLOWED_ORIGINS=["http://testserver"],
    )
    application = create_app(test_settings, database_runtime=phase2b_sqlite_runtime)

    with (
        patch("backend.main.validate_database_readiness"),
        patch("backend.main.compatibility.validate_compatibility_dataset"),
    ):
        application.state.request_authenticator = mock_authenticator
        application.state.clerk_profile_client = mock_authenticator
        yield application


@pytest.fixture
def client(phase2b_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(phase2b_app) as test_client:
        yield test_client


def test_unauthenticated_group_routes_return_401(client: TestClient) -> None:
    random_group_id = uuid.uuid4()
    assert client.get("/api/me/groups").status_code == 401
    assert (
        client.get(
            "/api/me/confirmed-sessions?start=2026-08-01&end=2026-08-31"
        ).status_code
        == 401
    )
    assert client.get(f"/api/groups/{random_group_id}").status_code == 401
    assert (
        client.get(
            f"/api/groups/{random_group_id}/confirmed-sessions?start=2026-08-01&end=2026-08-31"
        ).status_code
        == 401
    )
    assert (
        client.get(f"/api/groups/{random_group_id}/availability/2026/8").status_code
        == 401
    )
    assert (
        client.post(
            f"/api/groups/{random_group_id}/availability",
            json={"date": "2026-08-15", "status": "Available"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            f"/api/groups/{random_group_id}/admin/availability?start=2026-08-01&end=2026-08-31"
        ).status_code
        == 401
    )


def test_user_a_and_user_b_group_isolation(
    client: TestClient,
    mock_authenticator: MockRequestAuthenticator,
    phase2b_sqlite_runtime: DatabaseRuntime,
) -> None:
    session = phase2b_sqlite_runtime.open_session()

    # Create Group A (Fellowship) and Group B (Goblins)
    group_a = Group(id=uuid.uuid4(), name="Fellowship", timezone="UTC")
    group_b = Group(id=uuid.uuid4(), name="Goblins", timezone="UTC")
    session.add_all([group_a, group_b])
    session.commit()

    # User A setup
    token_a = "token-user-a"
    sub_a = "clerk_sub_user_a"
    mock_authenticator.add_session(
        token=token_a, subject=sub_a, email="a@example.com", display_name="Aragorn"
    )

    # /api/me provisions only Account A; the legacy DnD user is linked explicitly.
    resp_a = client.get("/api/me", headers={"Authorization": f"Bearer {token_a}"})
    assert resp_a.status_code == 200

    account_a = session.get(Account, uuid.UUID(resp_a.json()["id"]))
    assert account_a is not None
    user_a = User(
        id=uuid.uuid4(),
        account_id=account_a.id,
        display_name="Aragorn",
        timezone="UTC",
    )

    # Add User A to Group A (Owner)
    membership_a = GroupMembership(
        group_id=group_a.id,
        user_id=user_a.id,
        role=MembershipRole.OWNER,
        display_order=0,
    )
    session.add_all([user_a, membership_a])

    # User B setup
    token_b = "token-user-b"
    sub_b = "clerk_sub_user_b"
    mock_authenticator.add_session(
        token=token_b, subject=sub_b, email="b@example.com", display_name="Boromir"
    )

    resp_b = client.get("/api/me", headers={"Authorization": f"Bearer {token_b}"})
    assert resp_b.status_code == 200
    account_b = session.get(Account, uuid.UUID(resp_b.json()["id"]))
    assert account_b is not None
    user_b = User(
        id=uuid.uuid4(),
        account_id=account_b.id,
        display_name="Boromir",
        timezone="UTC",
    )

    # Add User B to Group B (Member)
    membership_b = GroupMembership(
        group_id=group_b.id,
        user_id=user_b.id,
        role=MembershipRole.MEMBER,
        display_order=0,
    )
    session.add_all([user_b, membership_b])
    session.commit()
    session.close()

    # User A queries /api/me/groups -> only Group A returned
    resp_my_groups_a = client.get(
        "/api/me/groups", headers={"Authorization": f"Bearer {token_a}"}
    )
    assert resp_my_groups_a.status_code == 200
    data_a = resp_my_groups_a.json()
    assert len(data_a) == 1
    assert data_a[0]["id"] == str(group_a.id)
    assert data_a[0]["name"] == "Fellowship"
    assert data_a[0]["role"] == "owner"

    # User A accesses own group A -> 200
    resp_group_a = client.get(
        f"/api/groups/{group_a.id}", headers={"Authorization": f"Bearer {token_a}"}
    )
    assert resp_group_a.status_code == 200
    assert resp_group_a.json()["name"] == "Fellowship"

    # User A attempts to access Group B -> 403 Forbidden!
    resp_forbidden = client.get(
        f"/api/groups/{group_b.id}", headers={"Authorization": f"Bearer {token_a}"}
    )
    assert resp_forbidden.status_code == 403
    assert resp_forbidden.json()["detail"] == "You are not a member of this group"

    # User B queries /api/me/groups -> only Group B returned
    resp_my_groups_b = client.get(
        "/api/me/groups", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert resp_my_groups_b.status_code == 200
    data_b = resp_my_groups_b.json()
    assert len(data_b) == 1
    assert data_b[0]["id"] == str(group_b.id)
    assert data_b[0]["role"] == "member"

    # User B attempts to access Group A -> 403 Forbidden!
    resp_forbidden_b = client.get(
        f"/api/groups/{group_a.id}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert resp_forbidden_b.status_code == 403


def test_authenticated_availability_update_and_admin_access(
    client: TestClient,
    mock_authenticator: MockRequestAuthenticator,
    phase2b_sqlite_runtime: DatabaseRuntime,
) -> None:
    session = phase2b_sqlite_runtime.open_session()
    group = Group(id=uuid.uuid4(), name="DragonSlayers", timezone="UTC")
    session.add(group)
    session.commit()

    # Owner user
    token_owner = "token-owner"
    mock_authenticator.add_session(
        token=token_owner,
        subject="sub_owner",
        display_name="DM Owner",
    )
    account_owner = resolve_or_provision_account(session, "clerk", "sub_owner")
    user_owner = User(
        id=uuid.uuid4(),
        account_id=account_owner.id,
        display_name="DM Owner",
        timezone="UTC",
    )

    # Member user
    token_member = "token-member"
    mock_authenticator.add_session(
        token=token_member,
        subject="sub_member",
        display_name="Player Member",
    )
    account_member = resolve_or_provision_account(session, "clerk", "sub_member")
    user_member = User(
        id=uuid.uuid4(),
        account_id=account_member.id,
        display_name="Player Member",
        timezone="UTC",
    )

    session.add_all(
        [
            user_owner,
            user_member,
            GroupMembership(
                group_id=group.id,
                user_id=user_owner.id,
                role=MembershipRole.OWNER,
                display_order=0,
            ),
            GroupMembership(
                group_id=group.id,
                user_id=user_member.id,
                role=MembershipRole.MEMBER,
                display_order=1,
            ),
        ]
    )
    session.commit()
    session.close()

    # A caller-supplied user_id cannot impersonate the owner; authentication wins.
    post_resp = client.post(
        f"/api/groups/{group.id}/availability",
        json={
            "date": "2026-08-15",
            "status": "Available",
            "user_id": str(user_owner.id),
        },
        headers={"Authorization": f"Bearer {token_member}"},
    )
    assert post_resp.status_code == 200
    assert post_resp.json()["status"] == "success"

    # Member queries monthly availability
    month_resp = client.get(
        f"/api/groups/{group.id}/availability/2026/8",
        headers={"Authorization": f"Bearer {token_member}"},
    )
    assert month_resp.status_code == 200
    entries = month_resp.json()
    assert len(entries) == 1
    assert entries[0]["user_id"] == str(user_member.id)
    assert entries[0]["date"] == "2026-08-15"
    assert entries[0]["status"] == "Available"

    # Member tries to access Owner Admin route -> 403 Forbidden!
    admin_resp_member = client.get(
        f"/api/groups/{group.id}/admin/availability?start=2026-08-01&end=2026-08-31",
        headers={"Authorization": f"Bearer {token_member}"},
    )
    assert admin_resp_member.status_code == 403
    assert "Only group owners" in admin_resp_member.json()["detail"]

    # Owner accesses Owner Admin route -> 200 OK
    admin_resp_owner = client.get(
        f"/api/groups/{group.id}/admin/availability?start=2026-08-01&end=2026-08-31",
        headers={"Authorization": f"Bearer {token_owner}"},
    )
    assert admin_resp_owner.status_code == 200
    assert len(admin_resp_owner.json()) == 1


def test_confirmed_sessions_are_owner_managed_and_member_scoped(
    client: TestClient,
    mock_authenticator: MockRequestAuthenticator,
    phase2b_sqlite_runtime: DatabaseRuntime,
) -> None:
    session = phase2b_sqlite_runtime.open_session()
    group = Group(id=uuid.uuid4(), name="Fellowship", timezone="UTC")
    second_group = Group(id=uuid.uuid4(), name="Underdark", timezone="UTC")
    private_group = Group(id=uuid.uuid4(), name="Private", timezone="UTC")
    session.add_all([group, second_group, private_group])
    session.commit()

    users: dict[str, User] = {}
    tokens = {
        "owner": "confirmed-owner-token",
        "member": "confirmed-member-token",
        "other_owner": "confirmed-other-owner-token",
        "outsider": "confirmed-outsider-token",
    }
    for key, token in tokens.items():
        subject = f"confirmed-{key}-subject"
        mock_authenticator.add_session(token=token, subject=subject, display_name=key)
        account = resolve_or_provision_account(session, "clerk", subject)
        users[key] = User(
            id=uuid.uuid4(),
            account_id=account.id,
            display_name=key,
            timezone="UTC",
        )

    session.add_all(
        [
            *users.values(),
            GroupMembership(
                group_id=group.id,
                user_id=users["owner"].id,
                role=MembershipRole.OWNER,
                display_order=0,
            ),
            GroupMembership(
                group_id=group.id,
                user_id=users["member"].id,
                role=MembershipRole.MEMBER,
                display_order=1,
            ),
            GroupMembership(
                group_id=second_group.id,
                user_id=users["other_owner"].id,
                role=MembershipRole.OWNER,
                display_order=0,
            ),
            GroupMembership(
                group_id=second_group.id,
                user_id=users["member"].id,
                role=MembershipRole.MEMBER,
                display_order=1,
            ),
            GroupMembership(
                group_id=private_group.id,
                user_id=users["outsider"].id,
                role=MembershipRole.OWNER,
                display_order=0,
            ),
            Availability(
                user_id=users["member"].id,
                day=date(2026, 8, 20),
                status=AvailabilityStatus.AVAILABLE,
            ),
            ConfirmedSession(
                group_id=second_group.id,
                day=date(2026, 8, 20),
                confirmed_by_user_id=users["other_owner"].id,
            ),
            ConfirmedSession(
                group_id=private_group.id,
                day=date(2026, 8, 21),
                confirmed_by_user_id=users["outsider"].id,
            ),
        ]
    )
    session.commit()

    headers = {
        key: {"Authorization": f"Bearer {token}"} for key, token in tokens.items()
    }
    confirmed_day = "2026-08-20"

    # Only the owner can confirm or cancel, and confirmation changes no availability.
    member_put = client.put(
        f"/api/groups/{group.id}/confirmed-sessions/{confirmed_day}",
        headers=headers["member"],
    )
    assert member_put.status_code == 403
    owner_put = client.put(
        f"/api/groups/{group.id}/confirmed-sessions/{confirmed_day}",
        headers=headers["owner"],
    )
    assert owner_put.status_code == 200
    first_session_id = owner_put.json()["id"]
    assert owner_put.json()["group_id"] == str(group.id)
    assert owner_put.json()["day"] == confirmed_day

    duplicate_put = client.put(
        f"/api/groups/{group.id}/confirmed-sessions/{confirmed_day}",
        headers=headers["owner"],
    )
    assert duplicate_put.status_code == 200
    assert duplicate_put.json()["id"] == first_session_id

    session.expire_all()
    assert (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(ConfirmedSession)
            .where(
                ConfirmedSession.group_id == group.id,
                ConfirmedSession.day == date(2026, 8, 20),
            )
        )
        == 1
    )
    availability = session.get(Availability, (users["member"].id, date(2026, 8, 20)))
    assert availability is not None
    assert availability.status == AvailabilityStatus.AVAILABLE

    member_get = client.get(
        f"/api/groups/{group.id}/confirmed-sessions?start=2026-08-01&end=2026-08-31",
        headers=headers["member"],
    )
    assert member_get.status_code == 200
    assert [entry["id"] for entry in member_get.json()] == [first_session_id]

    outsider_get = client.get(
        f"/api/groups/{group.id}/confirmed-sessions?start=2026-08-01&end=2026-08-31",
        headers=headers["outsider"],
    )
    assert outsider_get.status_code == 403
    member_delete = client.delete(
        f"/api/groups/{group.id}/confirmed-sessions/{confirmed_day}",
        headers=headers["member"],
    )
    assert member_delete.status_code == 403

    my_sessions = client.get(
        "/api/me/confirmed-sessions?start=2026-08-01&end=2026-08-31",
        headers=headers["member"],
    )
    assert my_sessions.status_code == 200
    assert {
        (entry["group_id"], entry["group_name"], entry["day"])
        for entry in my_sessions.json()
    } == {
        (str(group.id), "Fellowship", confirmed_day),
        (str(second_group.id), "Underdark", confirmed_day),
    }

    owner_delete = client.delete(
        f"/api/groups/{group.id}/confirmed-sessions/{confirmed_day}",
        headers=headers["owner"],
    )
    assert owner_delete.status_code == 200
    session.expire_all()
    assert (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(ConfirmedSession)
            .where(ConfirmedSession.group_id == group.id)
        )
        == 0
    )
    unchanged_availability = session.get(
        Availability,
        (users["member"].id, date(2026, 8, 20)),
    )
    assert unchanged_availability is not None
    assert unchanged_availability.status == AvailabilityStatus.AVAILABLE
    session.close()


def test_operator_link_account_to_user(
    phase2b_sqlite_runtime: DatabaseRuntime,
) -> None:
    session = phase2b_sqlite_runtime.open_session()

    account = Account(
        id=uuid.uuid4(), email="legacy_claim@example.com", display_name="Claimer"
    )
    user = User(id=uuid.uuid4(), display_name="Legacy Frodo", timezone="UTC")
    other_account = Account(id=uuid.uuid4(), email="other@example.com")
    other_user = User(id=uuid.uuid4(), display_name="Legacy Sam", timezone="UTC")

    session.add_all([account, user, other_account, other_user])
    session.commit()

    # Link account to user
    res_account, res_user = link_account_to_user(session, account.id, user.id)
    assert res_user.account_id == account.id

    # Idempotent repeated call succeeds
    res_acc2, res_usr2 = link_account_to_user(session, account.id, user.id)
    assert res_usr2.account_id == account.id

    # Trying to link same user to different account fails
    with pytest.raises(LinkAccountError, match="already linked to a different Account"):
        link_account_to_user(session, other_account.id, user.id)

    # Trying to link same account to different user fails
    with pytest.raises(LinkAccountError, match="already linked to a different User"):
        link_account_to_user(session, account.id, other_user.id)

    # Nonexistent IDs fail
    with pytest.raises(LinkAccountError, match="does not exist"):
        link_account_to_user(session, uuid.uuid4(), user.id)
    with pytest.raises(LinkAccountError, match="does not exist"):
        link_account_to_user(session, account.id, uuid.uuid4())

    session.close()
