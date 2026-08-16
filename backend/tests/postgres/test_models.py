from __future__ import annotations

import uuid
from datetime import date

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db import (
    DatabaseConfigurationError,
    create_database_runtime,
    redact_database_url,
)
from backend.models import (
    Availability,
    AvailabilityStatus,
    ConfirmedSession,
    Group,
    GroupMembership,
    MembershipRole,
    User,
)


def _add_user(session: Session, name: str, **values: object) -> User:
    user = User(display_name=name, **values)
    session.add(user)
    session.flush()
    return user


def _add_group(session: Session, name: str, **values: object) -> Group:
    group = Group(name=name, **values)
    session.add(group)
    session.flush()
    return group


def _assert_integrity_error(session: Session, value: object) -> None:
    with pytest.raises(IntegrityError):
        with session.begin():
            session.add(value)
            session.flush()


def test_schema_catalog_contains_exact_phase_1_objects(
    postgres_engine: Engine,
) -> None:
    inspector = sa.inspect(postgres_engine)
    assert {
        "users",
        "groups",
        "group_memberships",
        "availability",
        "confirmed_sessions",
    }.issubset(
        inspector.get_table_names()
    )

    expected_primary_keys = {
        "users": ("pk_users", ["id"]),
        "groups": ("pk_groups", ["id"]),
        "group_memberships": (
            "pk_group_memberships",
            ["group_id", "user_id"],
        ),
        "availability": ("pk_availability", ["user_id", "day"]),
        "confirmed_sessions": ("pk_confirmed_sessions", ["id"]),
    }
    for table_name, (constraint_name, columns) in expected_primary_keys.items():
        primary_key = inspector.get_pk_constraint(table_name)
        assert primary_key["name"] == constraint_name
        assert primary_key["constrained_columns"] == columns

    for table_name, uuid_columns in {
        "users": {"id"},
        "groups": {"id"},
        "group_memberships": {"group_id", "user_id"},
        "availability": {"user_id"},
        "confirmed_sessions": {"id", "group_id", "confirmed_by_user_id"},
    }.items():
        columns = {
            column["name"]: column for column in inspector.get_columns(table_name)
        }
        for column_name in uuid_columns:
            assert isinstance(columns[column_name]["type"], postgresql.UUID)

    expected_checks = {
        "users": {
            "ck_users_display_name_not_blank",
            "ck_users_auth_identity_pair",
            "ck_users_email_not_blank",
            "ck_users_timezone_not_blank",
        },
        "groups": {"ck_groups_name_not_blank", "ck_groups_timezone_not_blank"},
        "group_memberships": {
            "ck_group_memberships_role",
            "ck_group_memberships_display_order",
        },
        "availability": {"ck_availability_status"},
    }
    for table_name, expected_names in expected_checks.items():
        assert {
            constraint["name"]
            for constraint in inspector.get_check_constraints(table_name)
        } == expected_names

    assert {
        constraint["name"] for constraint in inspector.get_unique_constraints("users")
    } == {"uq_users_auth_identity"}
    assert {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("group_memberships")
    } == {"uq_group_memberships_display_order"}

    user_indexes = {index["name"]: index for index in inspector.get_indexes("users")}
    assert {"ix_users_display_name", "uq_users_email_normalized"}.issubset(user_indexes)
    assert user_indexes["uq_users_email_normalized"]["unique"] is True
    assert "email IS NOT NULL" in str(
        user_indexes["uq_users_email_normalized"]["dialect_options"]["postgresql_where"]
    )

    membership_indexes = {
        index["name"]: index for index in inspector.get_indexes("group_memberships")
    }
    assert {
        "ix_group_memberships_user_id",
        "ix_group_memberships_group_role",
        "uq_group_memberships_one_owner",
    }.issubset(membership_indexes)
    owner_index = membership_indexes["uq_group_memberships_one_owner"]
    assert owner_index["unique"] is True
    owner_predicate = str(owner_index["dialect_options"]["postgresql_where"])
    assert "role" in owner_predicate and "owner" in owner_predicate
    assert {index["name"] for index in inspector.get_indexes("groups")} == {
        "ix_groups_name"
    }
    assert {index["name"] for index in inspector.get_indexes("availability")} == {
        "ix_availability_day_user_id"
    }
    assert {index["name"] for index in inspector.get_indexes("confirmed_sessions")} == {
        "ix_confirmed_sessions_day"
    }
    assert {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("confirmed_sessions")
    } == {"uq_confirmed_sessions_group_id_day"}

    foreign_keys = {
        foreign_key["name"]: foreign_key
        for table_name in ("group_memberships", "availability", "confirmed_sessions")
        for foreign_key in inspector.get_foreign_keys(table_name)
    }
    assert foreign_keys["fk_group_memberships_group_id_groups"]["options"] == {
        "ondelete": "CASCADE"
    }
    assert foreign_keys["fk_group_memberships_user_id_users"]["options"] == {
        "ondelete": "RESTRICT"
    }
    assert foreign_keys["fk_availability_user_id_users"]["options"] == {
        "ondelete": "CASCADE"
    }
    assert foreign_keys["fk_confirmed_sessions_group_id_groups"]["options"] == {
        "ondelete": "CASCADE"
    }
    assert foreign_keys["fk_confirmed_sessions_confirmed_by_user_id_users"][
        "options"
    ] == {"ondelete": "RESTRICT"}

    expected_nullability = {
        "users": {
            "id": False,
            "auth_provider": True,
            "auth_subject": True,
            "email": True,
            "display_name": False,
            "timezone": False,
            "created_at": False,
            "updated_at": False,
        },
        "groups": {
            "id": False,
            "name": False,
            "timezone": False,
            "description": True,
            "created_at": False,
            "updated_at": False,
        },
        "group_memberships": {
            "group_id": False,
            "user_id": False,
            "role": False,
            "display_order": False,
            "joined_at": False,
        },
        "availability": {
            "user_id": False,
            "day": False,
            "status": False,
            "updated_at": False,
        },
        "confirmed_sessions": {
            "id": False,
            "group_id": False,
            "day": False,
            "confirmed_by_user_id": False,
            "confirmed_at": False,
        },
    }
    for table_name, nullable_columns in expected_nullability.items():
        columns = {
            column["name"]: column for column in inspector.get_columns(table_name)
        }
        for column_name, nullable in nullable_columns.items():
            assert columns[column_name]["nullable"] is nullable

    membership_columns = {
        column["name"]: column for column in inspector.get_columns("group_memberships")
    }
    availability_columns = {
        column["name"]: column for column in inspector.get_columns("availability")
    }
    assert membership_columns["role"]["type"].length == 16
    assert availability_columns["status"]["type"].length == 16


def test_valid_enums_defaults_timestamps_and_duplicate_group_names(
    db_session: Session,
) -> None:
    with db_session.begin():
        owner = _add_user(db_session, "Owner")
        organizer = _add_user(db_session, "Organizer")
        member = _add_user(db_session, "Member")
        duplicate_name_user = _add_user(db_session, "Member")
        groups = [_add_group(db_session, "Same name") for _ in range(3)]
        db_session.add_all(
            [
                GroupMembership(
                    group_id=groups[0].id,
                    user_id=owner.id,
                    role=MembershipRole.OWNER,
                    display_order=0,
                ),
                GroupMembership(
                    group_id=groups[1].id,
                    user_id=organizer.id,
                    role=MembershipRole.ORGANIZER,
                    display_order=0,
                ),
                GroupMembership(
                    group_id=groups[2].id,
                    user_id=member.id,
                    role=MembershipRole.MEMBER,
                    display_order=0,
                ),
            ]
        )
        db_session.add_all(
            [
                Availability(
                    user_id=duplicate_name_user.id,
                    day=date(2026, 1, day),
                    status=status,
                )
                for day, status in enumerate(AvailabilityStatus, start=1)
            ]
        )
        db_session.flush()

        assert owner.id is not None
        assert owner.timezone == "UTC"
        assert owner.created_at.tzinfo is not None
        assert owner.updated_at.tzinfo is not None
        assert groups[0].timezone == "UTC"
        assert groups[0].created_at.tzinfo is not None
        assert all(
            membership.joined_at.tzinfo is not None
            for membership in groups[0].memberships
        )


@pytest.mark.parametrize(
    "invalid_value",
    [
        User(display_name=""),
        User(display_name="Valid", timezone="  "),
        User(display_name="Valid", email=""),
        User(display_name="Valid", auth_provider="supabase"),
        User(display_name="Valid", auth_subject="subject"),
        Group(name=""),
        Group(name="Valid", timezone=" "),
    ],
)
def test_blank_and_half_identity_constraints_reject_invalid_rows(
    db_session: Session,
    invalid_value: object,
) -> None:
    _assert_integrity_error(db_session, invalid_value)


def test_identity_email_membership_and_availability_uniqueness(
    db_session: Session,
) -> None:
    with db_session.begin():
        first = _add_user(
            db_session,
            "First",
            auth_provider="supabase",
            auth_subject="subject-1",
            email="Player@Example.com",
        )
        second = _add_user(db_session, "Second")
        third = _add_user(db_session, "Third")
        fourth = _add_user(db_session, "Fourth")
        first_group = _add_group(db_session, "First group")
        second_group = _add_group(db_session, "Second group")
        db_session.add_all(
            [
                GroupMembership(
                    group_id=first_group.id,
                    user_id=first.id,
                    role=MembershipRole.OWNER,
                    display_order=0,
                ),
                GroupMembership(
                    group_id=second_group.id,
                    user_id=third.id,
                    role=MembershipRole.OWNER,
                    display_order=0,
                ),
            ]
        )
        first_id = first.id
        second_id = second.id
        third_id = third.id
        fourth_id = fourth.id
        first_group_id = first_group.id
        second_group_id = second_group.id

    _assert_integrity_error(
        db_session,
        User(
            display_name="Duplicate auth",
            auth_provider="supabase",
            auth_subject="subject-1",
        ),
    )
    _assert_integrity_error(
        db_session,
        User(display_name="Duplicate email", email="player@example.COM"),
    )
    _assert_integrity_error(
        db_session,
        GroupMembership(
            group_id=first_group_id,
            user_id=first_id,
            role=MembershipRole.MEMBER,
            display_order=1,
        ),
    )
    _assert_integrity_error(
        db_session,
        GroupMembership(
            group_id=first_group_id,
            user_id=second_id,
            role=MembershipRole.MEMBER,
            display_order=0,
        ),
    )

    with db_session.begin():
        db_session.add(
            GroupMembership(
                group_id=second_group_id,
                user_id=fourth_id,
                role=MembershipRole.MEMBER,
                display_order=1,
            )
        )
        db_session.add(
            Availability(
                user_id=second_id,
                day=date(2026, 2, 1),
                status=AvailabilityStatus.AVAILABLE,
            )
        )
        db_session.add(
            ConfirmedSession(
                group_id=first_group_id,
                day=date(2026, 2, 1),
                confirmed_by_user_id=first_id,
            )
        )

    _assert_integrity_error(
        db_session,
        Availability(
            user_id=second_id,
            day=date(2026, 2, 1),
            status=AvailabilityStatus.MAYBE,
        ),
    )
    _assert_integrity_error(
        db_session,
        ConfirmedSession(
            group_id=first_group_id,
            day=date(2026, 2, 1),
            confirmed_by_user_id=first_id,
        ),
    )

    with db_session.begin():
        db_session.add(
            Availability(
                user_id=third_id,
                day=date(2026, 2, 1),
                status=AvailabilityStatus.UNAVAILABLE,
            )
        )


def test_postgresql_checks_reject_raw_invalid_enum_values(db_session: Session) -> None:
    with db_session.begin():
        user = _add_user(db_session, "User")
        group = _add_group(db_session, "Group")

    with pytest.raises(IntegrityError):
        with db_session.begin():
            db_session.execute(
                sa.text(
                    "INSERT INTO group_memberships "
                    "(group_id, user_id, role, display_order) "
                    "VALUES (:group_id, :user_id, :role, 0)"
                ),
                {"group_id": group.id, "user_id": user.id, "role": "invalid"},
            )

    with pytest.raises(IntegrityError):
        with db_session.begin():
            db_session.execute(
                sa.text(
                    "INSERT INTO availability (user_id, day, status) "
                    "VALUES (:user_id, :day, :status)"
                ),
                {"user_id": user.id, "day": date(2026, 3, 1), "status": "invalid"},
            )


def test_delete_behaviors_are_enforced_by_postgresql(db_session: Session) -> None:
    with db_session.begin():
        owner = _add_user(db_session, "Owner")
        eligible = _add_user(db_session, "Eligible")
        group = _add_group(db_session, "Group")
        db_session.add(
            GroupMembership(
                group_id=group.id,
                user_id=owner.id,
                role=MembershipRole.OWNER,
                display_order=0,
            )
        )
        db_session.add_all(
            [
                Availability(
                    user_id=owner.id,
                    day=date(2026, 4, 1),
                    status=AvailabilityStatus.AVAILABLE,
                ),
                Availability(
                    user_id=eligible.id,
                    day=date(2026, 4, 1),
                    status=AvailabilityStatus.MAYBE,
                ),
                ConfirmedSession(
                    group_id=group.id,
                    day=date(2026, 4, 1),
                    confirmed_by_user_id=owner.id,
                ),
            ]
        )

    with pytest.raises(IntegrityError):
        with db_session.begin():
            db_session.delete(owner)
            db_session.flush()

    with db_session.begin():
        db_session.delete(group)
        db_session.flush()
    with db_session.begin():
        assert db_session.get(User, owner.id) is not None
        assert db_session.get(Availability, (owner.id, date(2026, 4, 1))) is not None
        assert db_session.get(GroupMembership, (group.id, owner.id)) is None
        assert (
            db_session.scalar(
                sa.select(sa.func.count())
                .select_from(ConfirmedSession)
                .where(ConfirmedSession.group_id == group.id)
            )
            == 0
        )

    with db_session.begin():
        db_session.delete(eligible)
        db_session.flush()
    with db_session.begin():
        assert db_session.get(Availability, (eligible.id, date(2026, 4, 1))) is None


def test_runtime_instances_are_isolated_and_diagnostics_are_redacted(
    postgres_database_url: str,
) -> None:
    first = create_database_runtime(postgres_database_url)
    second = create_database_runtime(postgres_database_url)
    try:
        assert first.engine is not second.engine
        assert first.session_factory is not second.session_factory
        assert "***" in repr(first)
        assert "dnd_planner_local_only" not in repr(first)

        first.dispose()
        with second.open_session() as session:
            assert session.scalar(sa.select(sa.literal(1))) == 1
    finally:
        first.dispose()
        second.dispose()

    assert "***" in redact_database_url(postgres_database_url)
    with pytest.raises(DatabaseConfigurationError) as exc_info:
        create_database_runtime("postgresql+psycopg://user:secret@")
    assert "secret" not in str(exc_info.value)

    with pytest.raises(DatabaseConfigurationError):
        create_database_runtime("sqlite:///not-allowed.db")


def test_uuid_python_defaults_produce_uuid4_values(db_session: Session) -> None:
    with db_session.begin():
        user = _add_user(db_session, "UUID user")
        group = _add_group(db_session, "UUID group")
    assert isinstance(user.id, uuid.UUID) and user.id.version == 4
    assert isinstance(group.id, uuid.UUID) and group.id.version == 4
