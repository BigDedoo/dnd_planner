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
    GroupInvite,
    GroupMembership,
    MembershipRole,
    SessionNotificationDelivery,
    SessionNotificationKind,
    SessionRsvp,
    User,
)
from backend.notifications import process_session_reminders


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

    with patch("backend.main.validate_database_readiness"):
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
    assert client.post("/api/groups", json={"name": "Unauthorized"}).status_code == 401
    assert (
        client.post("/api/groups/join", json={"code": "K7M4-PQ2X"}).status_code == 401
    )
    assert (
        client.post(
            "/api/group-invites/preview", json={"code": "K7M4-PQ2X"}
        ).status_code
        == 401
    )
    assert client.get(f"/api/groups/{random_group_id}/invite").status_code == 401
    assert client.post(f"/api/groups/{random_group_id}/invite").status_code == 401
    assert client.delete(f"/api/groups/{random_group_id}/invite").status_code == 401
    assert (
        client.patch(
            f"/api/groups/{random_group_id}/me", json={"nickname": "Nope"}
        ).status_code
        == 401
    )
    assert (
        client.patch(
            f"/api/groups/{random_group_id}", json={"name": "Unauthorized"}
        ).status_code
        == 401
    )
    assert client.post(f"/api/groups/{random_group_id}/leave").status_code == 401
    assert (
        client.delete(
            f"/api/groups/{random_group_id}/members/{uuid.uuid4()}"
        ).status_code
        == 401
    )
    assert (
        client.patch(
            f"/api/groups/{random_group_id}/members/{uuid.uuid4()}/role",
            json={"role": "organizer"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            f"/api/groups/{random_group_id}/transfer-ownership",
            json={"user_id": str(uuid.uuid4())},
        ).status_code
        == 401
    )
    assert client.delete(f"/api/groups/{random_group_id}").status_code == 401
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
        "organizer": "confirmed-organizer-token",
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
                group_id=group.id,
                user_id=users["organizer"].id,
                role=MembershipRole.ORGANIZER,
                display_order=2,
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

    # Owners and organizers schedule sessions; members cannot mutate them.
    member_put = client.put(
        f"/api/groups/{group.id}/confirmed-sessions/{confirmed_day}",
        headers=headers["member"],
    )
    assert member_put.status_code == 403
    owner_put = client.put(
        f"/api/groups/{group.id}/confirmed-sessions/{confirmed_day}",
        json={
            "title": "The Amber Gate",
            "start_time": "19:00",
            "duration_minutes": 240,
            "notes": "Bring your character sheet.",
        },
        headers=headers["owner"],
    )
    assert owner_put.status_code == 200
    first_session_id = owner_put.json()["id"]
    assert owner_put.json()["group_id"] == str(group.id)
    assert owner_put.json()["day"] == confirmed_day
    assert owner_put.json()["title"] == "The Amber Gate"
    assert owner_put.json()["start_time"] == "19:00:00"
    assert owner_put.json()["duration_minutes"] == 240

    duplicate_put = client.put(
        f"/api/groups/{group.id}/confirmed-sessions/{confirmed_day}",
        headers=headers["owner"],
    )
    assert duplicate_put.status_code == 200
    assert duplicate_put.json()["id"] == first_session_id

    organizer_patch = client.patch(
        f"/api/groups/{group.id}/confirmed-sessions/{confirmed_day}",
        json={"title": "The Amber Gate, revisited", "notes": "Bring dice."},
        headers=headers["organizer"],
    )
    assert organizer_patch.status_code == 200
    assert organizer_patch.json()["title"] == "The Amber Gate, revisited"
    assert organizer_patch.json()["start_time"] == "19:00:00"

    member_patch = client.patch(
        f"/api/groups/{group.id}/confirmed-sessions/{confirmed_day}",
        json={"title": "Not allowed"},
        headers=headers["member"],
    )
    assert member_patch.status_code == 403

    member_rsvp = client.put(
        f"/api/groups/{group.id}/confirmed-sessions/{confirmed_day}/rsvp",
        json={"status": "going"},
        headers=headers["member"],
    )
    assert member_rsvp.status_code == 200
    assert member_rsvp.json()["my_rsvp"] == "going"
    assert [
        (entry["user_id"], entry["status"]) for entry in member_rsvp.json()["rsvps"]
    ] == [(str(users["member"].id), "going")]
    member_rsvp_again = client.put(
        f"/api/groups/{group.id}/confirmed-sessions/{confirmed_day}/rsvp",
        json={"status": "maybe"},
        headers=headers["member"],
    )
    assert member_rsvp_again.status_code == 200
    assert member_rsvp_again.json()["my_rsvp"] == "maybe"

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
    assert session.scalar(sa.select(sa.func.count()).select_from(SessionRsvp)) == 1

    member_get = client.get(
        f"/api/groups/{group.id}/confirmed-sessions?start=2026-08-01&end=2026-08-31",
        headers=headers["member"],
    )
    assert member_get.status_code == 200
    assert [entry["id"] for entry in member_get.json()] == [first_session_id]
    assert member_get.json()[0]["rsvps"][0]["status"] == "maybe"

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
    assert (
        next(
            entry for entry in my_sessions.json() if entry["group_id"] == str(group.id)
        )["my_rsvp"]
        == "maybe"
    )

    organizer_delete = client.delete(
        f"/api/groups/{group.id}/confirmed-sessions/{confirmed_day}",
        headers=headers["organizer"],
    )
    assert organizer_delete.status_code == 200
    session.expire_all()
    cancelled_session = session.scalar(
        sa.select(ConfirmedSession).where(ConfirmedSession.group_id == group.id)
    )
    assert cancelled_session is not None
    assert cancelled_session.cancelled_at is not None
    assert cancelled_session.cancelled_by_user_id == users["organizer"].id
    assert (
        client.get(
            f"/api/groups/{group.id}/confirmed-sessions?start=2026-08-01&end=2026-08-31",
            headers=headers["member"],
        ).json()
        == []
    )
    cancelled_rows = client.get(
        f"/api/groups/{group.id}/confirmed-sessions?start=2026-08-01&end=2026-08-31&include_cancelled=true",
        headers=headers["member"],
    ).json()
    assert [entry["id"] for entry in cancelled_rows] == [first_session_id]
    assert cancelled_rows[0]["cancelled_at"] is not None
    unchanged_availability = session.get(
        Availability,
        (users["member"].id, date(2026, 8, 20)),
    )
    assert unchanged_availability is not None
    assert unchanged_availability.status == AvailabilityStatus.AVAILABLE
    session.close()


def test_onboarding_and_group_nicknames(
    client: TestClient,
    mock_authenticator: MockRequestAuthenticator,
    phase2b_sqlite_runtime: DatabaseRuntime,
) -> None:
    session = phase2b_sqlite_runtime.open_session()
    tokens = {
        "new": "onboarding-new-token",
        "owner": "onboarding-owner-token",
        "member": "onboarding-member-token",
    }
    users: dict[str, User] = {}
    for key, token in tokens.items():
        subject = f"onboarding-{key}-subject"
        mock_authenticator.add_session(
            token=token,
            subject=subject,
            username=f"{key}_username",
            display_name=f"{key.title()} account",
        )
        account = resolve_or_provision_account(session, "clerk", subject)
        if key != "new":
            users[key] = User(
                id=uuid.uuid4(),
                account_id=account.id,
                display_name=f"{key.title()} global",
                timezone="UTC",
            )
    legacy_user = User(id=uuid.uuid4(), display_name="Legacy user", timezone="UTC")
    group = Group(id=uuid.uuid4(), name="Nickname group", timezone="UTC")
    session.add_all(
        [
            *users.values(),
            legacy_user,
            group,
            GroupMembership(
                group_id=group.id,
                user_id=users["owner"].id,
                role=MembershipRole.OWNER,
                nickname="Dungeon Master",
                display_order=0,
            ),
            GroupMembership(
                group_id=group.id,
                user_id=users["member"].id,
                role=MembershipRole.MEMBER,
                display_order=1,
            ),
            GroupMembership(
                group_id=group.id,
                user_id=legacy_user.id,
                role=MembershipRole.MEMBER,
                display_order=2,
            ),
            Availability(
                user_id=users["owner"].id,
                day=date(2026, 9, 1),
                status=AvailabilityStatus.AVAILABLE,
            ),
            Availability(
                user_id=users["member"].id,
                day=date(2026, 9, 1),
                status=AvailabilityStatus.MAYBE,
            ),
        ]
    )
    session.commit()
    headers = {
        key: {"Authorization": f"Bearer {token}"} for key, token in tokens.items()
    }

    onboarding_status = client.get("/api/onboarding", headers=headers["new"])
    assert onboarding_status.status_code == 200
    assert onboarding_status.json() == {
        "linked": False,
        "suggested_display_name": "new_username",
        "user_id": None,
    }
    created = client.post(
        "/api/onboarding",
        headers=headers["new"],
        json={"display_name": "  New Adventurer  "},
    )
    assert created.status_code == 201
    new_user_id = uuid.UUID(created.json()["user_id"])
    new_user = session.get(User, new_user_id)
    assert new_user is not None
    assert new_user.display_name == "New Adventurer"
    assert new_user.account_id is not None
    repeated = client.post(
        "/api/onboarding",
        headers=headers["new"],
        json={"display_name": "A different name"},
    )
    assert repeated.status_code == 201
    assert repeated.json()["user_id"] == str(new_user_id)
    assert session.scalar(sa.select(sa.func.count()).select_from(User)) == 4
    assert client.get("/api/me/groups", headers=headers["new"]).status_code == 200

    linked_status = client.get("/api/onboarding", headers=headers["owner"])
    assert linked_status.status_code == 200
    assert linked_status.json()["linked"] is True
    assert client.post(
        "/api/onboarding",
        headers=headers["owner"],
        json={"display_name": "Should not replace global"},
    ).json()["user_id"] == str(users["owner"].id)
    assert users["owner"].display_name == "Owner global"

    detail = client.get(f"/api/groups/{group.id}", headers=headers["owner"])
    assert detail.status_code == 200
    members_by_id = {entry["id"]: entry for entry in detail.json()["members"]}
    assert members_by_id[str(users["owner"].id)]["display_name"] == "Dungeon Master"
    assert members_by_id[str(users["member"].id)]["display_name"] == "Member global"
    assert members_by_id[str(users["member"].id)]["nickname"] is None
    assert members_by_id[str(legacy_user.id)]["nickname"] is None

    member_update = client.patch(
        f"/api/groups/{group.id}/me",
        headers=headers["member"],
        json={"nickname": "Rogue"},
    )
    assert member_update.status_code == 200
    assert member_update.json()["display_name"] == "Rogue"
    assert (
        session.get(GroupMembership, (group.id, users["owner"].id)).nickname
        == "Dungeon Master"
    )
    assert (
        session.get(GroupMembership, (group.id, users["member"].id)).nickname == "Rogue"
    )
    assert users["member"].display_name == "Member global"
    assert session.get(Availability, (users["member"].id, date(2026, 9, 1))) is not None

    availability = client.get(
        f"/api/groups/{group.id}/availability/2026/9", headers=headers["member"]
    )
    assert {entry["user_name"] for entry in availability.json()} == {
        "Dungeon Master",
        "Rogue",
    }
    admin_availability = client.get(
        f"/api/groups/{group.id}/admin/availability?start=2026-09-01&end=2026-09-01",
        headers=headers["owner"],
    )
    assert {entry["user_name"] for entry in admin_availability.json()} == {
        "Dungeon Master",
        "Rogue",
    }
    cleared = client.patch(
        f"/api/groups/{group.id}/me",
        headers=headers["member"],
        json={"nickname": "   "},
    )
    assert cleared.status_code == 200
    assert cleared.json()["nickname"] is None
    assert cleared.json()["display_name"] == "Member global"
    session.close()


def test_group_creation_and_hashed_reusable_invites(
    client: TestClient,
    mock_authenticator: MockRequestAuthenticator,
    phase2b_sqlite_runtime: DatabaseRuntime,
) -> None:
    session = phase2b_sqlite_runtime.open_session()
    users: dict[str, User] = {}
    tokens = {
        "owner": "invite-owner-token",
        "member": "invite-member-token",
        "outsider": "invite-outsider-token",
    }
    for key, token in tokens.items():
        subject = f"invite-{key}-subject"
        mock_authenticator.add_session(token=token, subject=subject, display_name=key)
        account = resolve_or_provision_account(session, "clerk", subject)
        users[key] = User(
            id=uuid.uuid4(),
            account_id=account.id,
            display_name=key,
            timezone="UTC",
        )

    existing_group = Group(id=uuid.uuid4(), name="Existing group", timezone="UTC")
    session.add_all(
        [
            *users.values(),
            existing_group,
            GroupMembership(
                group_id=existing_group.id,
                user_id=users["owner"].id,
                role=MembershipRole.OWNER,
                display_order=0,
            ),
        ]
    )
    session.commit()
    headers = {
        key: {"Authorization": f"Bearer {token}"} for key, token in tokens.items()
    }

    created = client.post(
        "/api/groups",
        headers=headers["owner"],
        json={
            "name": "  Tomb of Annihilation  ",
            "description": "Jungle trek",
            "nickname": "Guide",
        },
    )
    assert created.status_code == 201
    created_group = created.json()
    group_id = uuid.UUID(created_group["id"])
    assert created_group == {
        "id": str(group_id),
        "name": "Tomb of Annihilation",
        "timezone": "UTC",
        "role": "owner",
    }
    membership = session.get(GroupMembership, (group_id, users["owner"].id))
    assert membership is not None
    assert membership.role == MembershipRole.OWNER
    assert membership.nickname == "Guide"
    assert membership.display_order == 0

    # Creating the membership fails after the group is flushed; the group rolls back too.
    def invalid_membership(**values: object) -> GroupMembership:
        return GroupMembership(**{**values, "display_order": -1})

    with patch("backend.main.GroupMembership", side_effect=invalid_membership):
        failed_create = client.post(
            "/api/groups",
            headers=headers["owner"],
            json={"name": "Must Roll Back"},
        )
    assert failed_create.status_code == 503
    session.expire_all()
    assert (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(Group)
            .where(Group.name == "Must Roll Back")
        )
        == 0
    )

    first_invite = client.post(
        f"/api/groups/{group_id}/invite", headers=headers["owner"]
    )
    assert first_invite.status_code == 200
    first_code = first_invite.json()["code"]
    assert len(first_code) == 9 and first_code[4] == "-"
    assert all(character not in "01IO" for character in first_code.replace("-", ""))
    assert (
        client.get(
            f"/api/groups/{group_id}/invite", headers=headers["member"]
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/groups/{group_id}/invite", headers=headers["member"]
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/groups/{group_id}/invite", headers=headers["member"]
        ).status_code
        == 403
    )

    regenerated = client.post(
        f"/api/groups/{group_id}/invite", headers=headers["owner"]
    )
    assert regenerated.status_code == 200
    second_code = regenerated.json()["code"]
    assert second_code != first_code
    session.expire_all()
    invite = session.scalar(
        sa.select(GroupInvite).where(
            GroupInvite.group_id == group_id,
            GroupInvite.revoked_at.is_(None),
        )
    )
    assert invite is not None
    assert invite.code_hash != second_code
    assert first_code not in invite.code_hash
    assert second_code not in invite.code_hash

    preview = client.post(
        "/api/group-invites/preview",
        headers=headers["member"],
        json={"code": second_code.lower().replace("-", "")},
    )
    assert preview.status_code == 200
    assert preview.json() == {"group_name": "Tomb of Annihilation"}

    old_code = client.post(
        "/api/groups/join",
        headers=headers["outsider"],
        json={"code": first_code},
    )
    assert old_code.status_code == 404
    joined = client.post(
        "/api/groups/join",
        headers=headers["member"],
        json={"code": second_code.lower().replace("-", ""), "nickname": "Scout"},
    )
    assert joined.status_code == 200
    assert joined.json()["joined"] is True
    assert joined.json()["role"] == "member"
    member_membership = session.get(GroupMembership, (group_id, users["member"].id))
    assert member_membership is not None
    assert member_membership.role == MembershipRole.MEMBER
    assert member_membership.nickname == "Scout"

    duplicate_join = client.post(
        "/api/groups/join",
        headers=headers["member"],
        json={"code": second_code},
    )
    assert duplicate_join.status_code == 200
    assert duplicate_join.json()["joined"] is False
    assert (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(GroupMembership)
            .where(GroupMembership.group_id == group_id)
        )
        == 2
    )
    session.expire_all()
    assert session.get(GroupInvite, invite.id).use_count == 1

    revoked = client.delete(f"/api/groups/{group_id}/invite", headers=headers["owner"])
    assert revoked.status_code == 200
    revoked_code = client.post(
        "/api/groups/join",
        headers=headers["outsider"],
        json={"code": second_code},
    )
    assert revoked_code.status_code == 404
    revoked_preview = client.post(
        "/api/group-invites/preview",
        headers=headers["member"],
        json={"code": second_code},
    )
    assert revoked_preview.status_code == 404
    for _ in range(3):
        assert (
            client.post(
                "/api/groups/join",
                headers=headers["outsider"],
                json={"code": "K7M4-PQ2X"},
            ).status_code
            == 404
        )
    assert (
        client.post(
            "/api/groups/join",
            headers=headers["outsider"],
            json={"code": "K7M4-PQ2X"},
        ).status_code
        == 429
    )
    assert (
        session.get(GroupMembership, (existing_group.id, users["owner"].id)) is not None
    )
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


def test_group_management_permissions_and_invariants(
    client: TestClient,
    mock_authenticator: MockRequestAuthenticator,
    phase2b_sqlite_runtime: DatabaseRuntime,
) -> None:
    session = phase2b_sqlite_runtime.open_session()
    tokens = {
        "owner": "management-owner-token",
        "organizer": "management-organizer-token",
        "member": "management-member-token",
        "removable": "management-removable-token",
        "outsider": "management-outsider-token",
    }
    users: dict[str, User] = {}
    for key, token in tokens.items():
        subject = f"management-{key}-subject"
        mock_authenticator.add_session(token=token, subject=subject, display_name=key)
        account = resolve_or_provision_account(session, "clerk", subject)
        users[key] = User(
            id=uuid.uuid4(),
            account_id=account.id,
            display_name=key.title(),
            timezone="UTC",
        )

    group = Group(id=uuid.uuid4(), name="Management group", timezone="UTC")
    unrelated_group = Group(id=uuid.uuid4(), name="Unrelated group", timezone="UTC")
    session.add_all(
        [
            *users.values(),
            group,
            unrelated_group,
            GroupMembership(
                group_id=group.id,
                user_id=users["owner"].id,
                role=MembershipRole.OWNER,
                display_order=0,
            ),
            GroupMembership(
                group_id=group.id,
                user_id=users["organizer"].id,
                role=MembershipRole.ORGANIZER,
                nickname="Quartermaster",
                display_order=1,
            ),
            GroupMembership(
                group_id=group.id,
                user_id=users["member"].id,
                role=MembershipRole.MEMBER,
                display_order=2,
            ),
            GroupMembership(
                group_id=group.id,
                user_id=users["removable"].id,
                role=MembershipRole.MEMBER,
                display_order=3,
            ),
            GroupMembership(
                group_id=unrelated_group.id,
                user_id=users["outsider"].id,
                role=MembershipRole.OWNER,
                display_order=0,
            ),
        ]
    )
    session.flush()
    session.add_all(
        [
            GroupInvite(
                group_id=group.id,
                code_hash="a" * 64,
                created_by_user_id=users["owner"].id,
            ),
            ConfirmedSession(
                group_id=group.id,
                day=date(2026, 9, 12),
                confirmed_by_user_id=users["owner"].id,
            ),
        ]
    )
    session.commit()
    session.close()

    headers = {
        key: {"Authorization": f"Bearer {token}"} for key, token in tokens.items()
    }

    detail = client.get(f"/api/groups/{group.id}", headers=headers["member"])
    assert detail.status_code == 200
    organizer_detail = next(
        member
        for member in detail.json()["members"]
        if member["id"] == str(users["organizer"].id)
    )
    assert organizer_detail["display_name"] == "Quartermaster"

    assert (
        client.get(f"/api/groups/{group.id}", headers=headers["outsider"]).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/groups/{group.id}", headers=headers["member"], json={"name": "No"}
        ).status_code
        == 403
    )
    renamed = client.patch(
        f"/api/groups/{group.id}",
        headers=headers["owner"],
        json={"name": "  The Keep  "},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "The Keep"

    # Organizers can remove ordinary members only and cannot escalate anyone.
    assert (
        client.patch(
            f"/api/groups/{group.id}/members/{users['member'].id}/role",
            headers=headers["organizer"],
            json={"role": "organizer"},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/groups/{group.id}/members/{users['organizer'].id}",
            headers=headers["organizer"],
        ).status_code
        == 403
    )
    removed = client.delete(
        f"/api/groups/{group.id}/members/{users['removable'].id}",
        headers=headers["organizer"],
    )
    assert removed.status_code == 200
    assert (
        client.post(
            f"/api/groups/{group.id}/transfer-ownership",
            headers=headers["organizer"],
            json={"user_id": str(users["member"].id)},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/groups/{group.id}", headers=headers["organizer"]
        ).status_code
        == 403
    )

    promoted = client.patch(
        f"/api/groups/{group.id}/members/{users['member'].id}/role",
        headers=headers["owner"],
        json={"role": "organizer"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "organizer"
    demoted = client.patch(
        f"/api/groups/{group.id}/members/{users['member'].id}/role",
        headers=headers["owner"],
        json={"role": "member"},
    )
    assert demoted.status_code == 200
    assert demoted.json()["role"] == "member"
    assert (
        client.patch(
            f"/api/groups/{group.id}/members/{users['owner'].id}/role",
            headers=headers["owner"],
            json={"role": "member"},
        ).status_code
        == 409
    )
    assert (
        client.delete(
            f"/api/groups/{group.id}/members/{users['owner'].id}",
            headers=headers["owner"],
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/groups/{group.id}/members/{users['outsider'].id}/role",
            headers=headers["owner"],
            json={"role": "organizer"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/groups/{group.id}/leave", headers=headers["owner"]
        ).status_code
        == 409
    )

    transferred = client.post(
        f"/api/groups/{group.id}/transfer-ownership",
        headers=headers["owner"],
        json={"user_id": str(users["member"].id)},
    )
    assert transferred.status_code == 200
    assert transferred.json()["role"] == "member"
    session = phase2b_sqlite_runtime.open_session()
    assert (
        session.get(GroupMembership, (group.id, users["owner"].id)).role
        == MembershipRole.MEMBER
    )
    assert (
        session.get(GroupMembership, (group.id, users["member"].id)).role
        == MembershipRole.OWNER
    )
    assert (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(GroupMembership)
            .where(
                GroupMembership.group_id == group.id,
                GroupMembership.role == MembershipRole.OWNER,
            )
        )
        == 1
    )
    assert (
        client.delete(f"/api/groups/{group.id}", headers=headers["owner"]).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/groups/{group.id}/leave", headers=headers["member"]
        ).status_code
        == 409
    )

    deleted = client.delete(f"/api/groups/{group.id}", headers=headers["member"])
    assert deleted.status_code == 204
    session.expire_all()
    assert session.get(Group, group.id) is None
    assert session.get(User, users["owner"].id) is not None
    assert session.get(Account, users["owner"].account_id) is not None
    assert (
        session.get(GroupMembership, (unrelated_group.id, users["outsider"].id))
        is not None
    )
    assert session.scalar(sa.select(sa.func.count()).select_from(GroupInvite)) == 0
    assert session.scalar(sa.select(sa.func.count()).select_from(ConfirmedSession)) == 0
    session.close()


def test_scheduling_wave_exports_cancellation_and_notifications(
    client: TestClient,
    mock_authenticator: MockRequestAuthenticator,
    phase2b_sqlite_runtime: DatabaseRuntime,
) -> None:
    db_session = phase2b_sqlite_runtime.open_session()
    users: dict[str, User] = {}
    for role in ("owner", "member"):
        token = f"wave-{role}-token"
        subject = f"wave-{role}-subject"
        mock_authenticator.add_session(token=token, subject=subject, display_name=role)
        account = resolve_or_provision_account(db_session, "clerk", subject)
        users[role] = User(
            id=uuid.uuid4(),
            account_id=account.id,
            display_name=role.title(),
            timezone="UTC",
        )
    group = Group(id=uuid.uuid4(), name="Wave group", timezone="UTC")
    db_session.add_all(
        [
            *users.values(),
            group,
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
        ]
    )
    db_session.commit()
    owner_headers = {"Authorization": "Bearer wave-owner-token"}
    member_headers = {"Authorization": "Bearer wave-member-token"}

    created = client.put(
        f"/api/groups/{group.id}/confirmed-sessions/2026-08-22",
        headers=owner_headers,
        json={
            "title": "The Wave",
            "start_time": "19:00",
            "duration_minutes": 180,
            "notes": "Bring dice",
        },
    )
    assert created.status_code == 200
    session_id = uuid.UUID(created.json()["id"])
    assert (
        db_session.scalar(
            sa.select(sa.func.count())
            .select_from(SessionNotificationDelivery)
            .where(
                SessionNotificationDelivery.kind == SessionNotificationKind.SCHEDULED
            )
        )
        == 2
    )

    individual_ics = client.get(
        f"/api/groups/{group.id}/confirmed-sessions/2026-08-22/calendar.ics",
        headers=member_headers,
    )
    assert individual_ics.status_code == 200
    assert individual_ics.headers["content-type"].startswith("text/calendar")
    assert "SUMMARY:The Wave" in individual_ics.text
    assert "DTSTART;TZID=UTC:20260822T190000" in individual_ics.text
    personal_ics = client.get(
        "/api/me/confirmed-sessions.ics?start=2026-08-01&end=2026-08-31",
        headers=member_headers,
    )
    assert personal_ics.status_code == 200
    assert personal_ics.text.count("BEGIN:VEVENT") == 1

    first_reminders = process_session_reminders(
        db_session, today=date(2026, 8, 20), days_ahead=7
    )
    assert first_reminders == {"upcoming": 2, "missing_rsvp": 2}
    second_reminders = process_session_reminders(
        db_session, today=date(2026, 8, 20), days_ahead=7
    )
    assert second_reminders == {"upcoming": 0, "missing_rsvp": 0}

    cancelled = client.delete(
        f"/api/groups/{group.id}/confirmed-sessions/2026-08-22",
        headers=owner_headers,
    )
    assert cancelled.status_code == 200
    db_session.expire_all()
    assert db_session.get(ConfirmedSession, session_id).cancelled_at is not None
    assert process_session_reminders(
        db_session, today=date(2026, 8, 20), days_ahead=7
    ) == {"upcoming": 0, "missing_rsvp": 0}
    assert (
        db_session.scalar(
            sa.select(sa.func.count())
            .select_from(SessionNotificationDelivery)
            .where(
                SessionNotificationDelivery.kind == SessionNotificationKind.CANCELLED
            )
        )
        == 2
    )
    db_session.close()


def test_product_wave_isolated_e2e_flow(
    client: TestClient,
    mock_authenticator: MockRequestAuthenticator,
) -> None:
    for role in ("owner", "member"):
        mock_authenticator.add_session(
            token=f"e2e-{role}-token",
            subject=f"e2e-{role}-subject",
            display_name=f"E2E {role}",
        )
    headers = {
        role: {"Authorization": f"Bearer e2e-{role}-token"}
        for role in ("owner", "member")
    }
    for role in ("owner", "member"):
        assert (
            client.post(
                "/api/onboarding",
                headers=headers[role],
                json={"display_name": f"E2E {role}"},
            ).status_code
            == 201
        )

    created_group = client.post(
        "/api/groups",
        headers=headers["owner"],
        json={"name": "E2E campaign"},
    )
    assert created_group.status_code == 201
    group_id = created_group.json()["id"]
    invite = client.post(
        f"/api/groups/{group_id}/invite", headers=headers["owner"]
    ).json()["code"]
    joined = client.post(
        "/api/groups/join",
        headers=headers["member"],
        json={"code": invite, "nickname": "Scout"},
    )
    assert joined.status_code == 200 and joined.json()["role"] == "member"

    for role, status_value in (("owner", "Available"), ("member", "Maybe")):
        response = client.post(
            f"/api/groups/{group_id}/availability",
            headers=headers[role],
            json={"date": "2026-08-29", "status": status_value},
        )
        assert response.status_code == 200
    availability = client.get(
        f"/api/groups/{group_id}/availability/2026/8",
        headers=headers["owner"],
    ).json()
    assert {entry["status"] for entry in availability} == {"Available", "Maybe"}

    scheduled = client.put(
        f"/api/groups/{group_id}/confirmed-sessions/2026-08-29",
        headers=headers["owner"],
        json={
            "title": "Recommended date",
            "start_time": "19:30",
            "duration_minutes": 180,
        },
    )
    assert scheduled.status_code == 200
    rsvp = client.put(
        f"/api/groups/{group_id}/confirmed-sessions/2026-08-29/rsvp",
        headers=headers["member"],
        json={"status": "going"},
    )
    assert rsvp.status_code == 200 and rsvp.json()["my_rsvp"] == "going"
    my_schedule = client.get(
        "/api/me/confirmed-sessions?start=2026-08-01&end=2026-08-31",
        headers=headers["member"],
    ).json()
    assert [
        (row["group_name"], row["title"], row["my_rsvp"]) for row in my_schedule
    ] == [("E2E campaign", "Recommended date", "going")]
    group_sessions = client.get(
        f"/api/groups/{group_id}/confirmed-sessions?start=2026-08-01&end=2026-08-31&include_cancelled=true",
        headers=headers["member"],
    ).json()
    assert [row["id"] for row in group_sessions] == [scheduled.json()["id"]]
