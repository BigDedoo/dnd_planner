from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa
from sqlalchemy import create_engine

from backend.auth import resolve_or_provision_account
from backend.clerk_profile import (
    ClerkProfile,
    ClerkSDKProfileClient,
    apply_clerk_profile,
    extract_clerk_profile,
    sync_account_profile_if_due,
)
from backend.db import DatabaseRuntime
from backend.models import (
    Account,
    AccountIdentity,
    Availability,
    AvailabilityStatus,
    Base,
    Group,
    GroupMembership,
    MembershipRole,
    User,
)


def _verification(status: str = "verified") -> SimpleNamespace:
    return SimpleNamespace(status=status)


def _email(
    address_id: str,
    value: str,
    status: str = "verified",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=address_id,
        email_address=value,
        verification=_verification(status),
    )


def _external(
    provider: str,
    username: object,
    status: str = "verified",
) -> SimpleNamespace:
    return SimpleNamespace(
        provider=provider,
        username=username,
        verification=_verification(status),
    )


def _clerk_user(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "primary_email_address_id": None,
        "email_addresses": [],
        "username": None,
        "full_name": None,
        "first_name": None,
        "last_name": None,
        "external_accounts": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_extracts_primary_verified_email_username_and_full_name() -> None:
    user = _clerk_user(
        primary_email_address_id="email_primary",
        email_addresses=[
            _email("email_other", "other@example.com"),
            _email("email_primary", " Player@Example.com "),
        ],
        username="  dungeon   master  ",
        first_name="  Ada  ",
        last_name=" Lovelace ",
    )

    assert extract_clerk_profile(user) == ClerkProfile(
        email="player@example.com",
        username="dungeon master",
        display_name="Ada Lovelace",
    )


def test_discord_username_is_preferred_social_fallback() -> None:
    user = _clerk_user(
        external_accounts=[
            _external("oauth_google", "google-name"),
            _external("oauth_discord", "discord-name"),
        ]
    )

    assert extract_clerk_profile(user) == ClerkProfile(
        email=None,
        username="discord-name",
        display_name="discord-name",
    )


def test_other_verified_social_username_is_used_deterministically() -> None:
    user = _clerk_user(
        external_accounts=[
            _external("oauth_twitch", "twitch-name"),
            _external("oauth_github", "github-name"),
            _external("oauth_discord", "unverified-discord", status="unverified"),
        ]
    )

    assert extract_clerk_profile(user).username == "github-name"


def test_missing_or_unverified_email_and_username_remain_null() -> None:
    user = _clerk_user(
        primary_email_address_id="email_primary",
        email_addresses=[
            _email("email_primary", "unverified@example.com", status="unverified")
        ],
        external_accounts=[
            _external("oauth_discord", "unverified-name", status="failed")
        ],
    )

    assert extract_clerk_profile(user) == ClerkProfile(None, None, None)


def test_blank_profile_values_are_normalized_to_null() -> None:
    user = _clerk_user(
        username=" \t ",
        full_name="\n",
        first_name=" ",
        last_name="",
        external_accounts=[_external("oauth_discord", "   ")],
    )

    assert extract_clerk_profile(user) == ClerkProfile(None, None, None)


def test_sdk_profile_client_uses_supported_users_get_operation() -> None:
    captured: dict[str, str] = {}
    user = _clerk_user(username="sdk-user")

    def get_user(*, user_id: str) -> SimpleNamespace:
        captured["user_id"] = user_id
        return user

    client = ClerkSDKProfileClient("sk_test_not_a_real_secret")
    client._client = SimpleNamespace(users=SimpleNamespace(get=get_user))

    assert client.fetch_profile("user_sdk_subject").username == "sdk-user"
    assert captured == {"user_id": "user_sdk_subject"}


class FakeProfileClient:
    def __init__(self, profile: ClerkProfile | None = None) -> None:
        self.profile = profile or ClerkProfile(None, None, None)
        self.calls: list[str] = []
        self.fail = False

    def fetch_profile(self, clerk_user_id: str) -> ClerkProfile:
        self.calls.append(clerk_user_id)
        if self.fail:
            raise RuntimeError("temporary Clerk failure")
        return self.profile


def _runtime(tmp_path: Path) -> Iterator[DatabaseRuntime]:
    engine = create_engine(f"sqlite:///{tmp_path / 'profile_test.db'}")

    @sa.event.listens_for(engine, "connect")
    def _register_sqlite_functions(dbapi_connection, _):
        dbapi_connection.create_function(
            "btrim", 1, lambda value: value.strip() if value is not None else None
        )

    Base.metadata.create_all(engine)
    runtime = DatabaseRuntime(engine=engine, safe_url="sqlite:///profile_test.db")
    try:
        yield runtime
    finally:
        runtime.dispose()


def test_existing_incomplete_account_is_enriched_without_duplicates(
    tmp_path: Path,
) -> None:
    runtime_generator = _runtime(tmp_path)
    runtime = next(runtime_generator)
    try:
        with runtime.open_session() as session:
            account = resolve_or_provision_account(session, "clerk", "user_existing")
            account_id = account.id
            client = FakeProfileClient(
                ClerkProfile("player@example.com", "player", "Player One")
            )

            synced = sync_account_profile_if_due(
                session, account, "user_existing", client
            )

            assert synced.id == account_id
            assert synced.email == "player@example.com"
            assert synced.username == "player"
            assert synced.display_name == "Player One"
            assert synced.profile_synced_at is not None
            assert session.query(Account).count() == 1
            assert session.query(AccountIdentity).count() == 1
    finally:
        runtime_generator.close()


def test_recent_profile_skips_lookup_and_stale_profile_refreshes(
    tmp_path: Path,
) -> None:
    runtime_generator = _runtime(tmp_path)
    runtime = next(runtime_generator)
    now = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)
    try:
        with runtime.open_session() as session:
            account = resolve_or_provision_account(session, "clerk", "user_refresh")
            account.profile_synced_at = now - timedelta(hours=23)
            session.commit()
            client = FakeProfileClient(ClerkProfile(None, "new-name", "New Name"))

            sync_account_profile_if_due(session, account, "user_refresh", client, now)
            assert client.calls == []

            account.profile_synced_at = now - timedelta(hours=25)
            session.commit()
            sync_account_profile_if_due(session, account, "user_refresh", client, now)
            assert client.calls == ["user_refresh"]
            assert account.username == "new-name"
            assert account.display_name == "New Name"
    finally:
        runtime_generator.close()


def test_profile_failure_preserves_existing_account_and_allows_retry(
    tmp_path: Path,
) -> None:
    runtime_generator = _runtime(tmp_path)
    runtime = next(runtime_generator)
    try:
        with runtime.open_session() as session:
            account = resolve_or_provision_account(
                session,
                "clerk",
                "user_failure",
                email="existing@example.com",
                display_name="Existing Name",
            )
            account_id = account.id
            client = FakeProfileClient(
                ClerkProfile("new@example.com", "new-name", "New Name")
            )
            client.fail = True

            failed = sync_account_profile_if_due(
                session, account, "user_failure", client
            )
            assert failed.id == account_id
            assert failed.email == "existing@example.com"
            assert failed.display_name == "Existing Name"
            assert failed.profile_synced_at is None

            client.fail = False
            retried = sync_account_profile_if_due(
                session, failed, "user_failure", client
            )
            assert retried.id == account_id
            assert retried.email == "new@example.com"
            assert retried.profile_synced_at is not None
    finally:
        runtime_generator.close()


def test_new_identity_survives_profile_failure_idempotently(tmp_path: Path) -> None:
    runtime_generator = _runtime(tmp_path)
    runtime = next(runtime_generator)
    try:
        with runtime.open_session() as session:
            client = FakeProfileClient()
            client.fail = True
            first = resolve_or_provision_account(session, "clerk", "user_new_failure")
            first_id = first.id

            sync_account_profile_if_due(session, first, "user_new_failure", client)
            second = resolve_or_provision_account(session, "clerk", "user_new_failure")

            assert second.id == first_id
            assert second.profile_synced_at is None
            assert session.query(Account).count() == 1
            assert session.query(AccountIdentity).count() == 1
    finally:
        runtime_generator.close()


def test_email_collision_never_merges_or_relinks_accounts(tmp_path: Path) -> None:
    runtime_generator = _runtime(tmp_path)
    runtime = next(runtime_generator)
    try:
        with runtime.open_session() as session:
            account_a = resolve_or_provision_account(
                session, "clerk", "subject_a", email="player@example.com"
            )
            account_b = resolve_or_provision_account(session, "clerk", "subject_b")
            a_id = account_a.id
            b_id = account_b.id

            apply_clerk_profile(
                session,
                account_b,
                ClerkProfile("PLAYER@example.com", "player-b", "Player B"),
            )

            session.expire_all()
            account_a = session.get(Account, a_id)
            account_b = session.get(Account, b_id)
            assert account_a is not None and account_b is not None
            assert account_a.email == "player@example.com"
            assert account_b.email is None
            assert account_b.username == "player-b"
            assert account_b.display_name == "Player B"
            assert account_a.id != account_b.id
            assert {identity.provider_subject for identity in account_a.identities} == {
                "subject_a"
            }
            assert {identity.provider_subject for identity in account_b.identities} == {
                "subject_b"
            }
    finally:
        runtime_generator.close()


def test_profile_changes_do_not_change_authorization_identity(tmp_path: Path) -> None:
    runtime_generator = _runtime(tmp_path)
    runtime = next(runtime_generator)
    try:
        with runtime.open_session() as session:
            account = resolve_or_provision_account(
                session, "clerk", "stable_subject", email="old@example.com"
            )
            user = User(
                id=uuid.uuid4(),
                account_id=account.id,
                display_name="Legacy Player",
            )
            group = Group(id=uuid.uuid4(), name="Stable Group")
            membership = GroupMembership(
                group_id=group.id,
                user_id=user.id,
                role=MembershipRole.OWNER,
                display_order=0,
            )
            availability = Availability(
                user_id=user.id,
                day=date(2026, 8, 16),
                status=AvailabilityStatus.AVAILABLE,
            )
            session.add_all([user, group, membership, availability])
            session.commit()
            account_id = account.id
            identity_id = account.identities[0].id
            membership_key = (group.id, user.id)
            availability_key = (user.id, date(2026, 8, 16))

            apply_clerk_profile(
                session,
                account,
                ClerkProfile("changed@example.com", "changed", "Changed Name"),
            )

            assert account.id == account_id
            identity = session.get(AccountIdentity, identity_id)
            assert identity is not None
            assert identity.provider_subject == "stable_subject"
            assert session.get(User, user.id).account_id == account_id
            assert session.get(GroupMembership, membership_key) is not None
            assert session.get(Availability, availability_key) is not None
    finally:
        runtime_generator.close()
