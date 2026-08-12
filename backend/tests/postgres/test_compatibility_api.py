from __future__ import annotations

import importlib
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend import compatibility, database
from backend.cli import import_legacy_sqlite as importer
from backend.config import Settings
from backend.db import (
    DatabaseReadinessError,
    DatabaseRuntime,
    create_database_runtime,
)
from backend.legacy_contract import GROUPS, deterministic_legacy_uuid
from backend.main import create_app
from backend.models import (
    Availability,
    AvailabilityStatus,
    Group,
    GroupMembership,
    MembershipRole,
    User,
)
from backend.tests.postgres.test_import_legacy_sqlite import (
    apply_arguments,
    prepare_plan,
)
from backend.tests.test_import_legacy_sqlite import file_evidence

EXPECTED_GROUPS = [
    {"name": name, "players": list(players)} for name, players in GROUPS.items()
]
OWNER_BY_GROUP = {
    "Green flag": "Quentin",
    "1D6": "Gaelle",
    "Underdark": "Dembe",
}
FIXED_TIMESTAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)


def seed_legacy_dataset(
    session: Session,
    *,
    omit_group: str | None = None,
    availability: list[tuple[str, date, AvailabilityStatus]] | None = None,
) -> None:
    user_ids = {
        user_name: deterministic_legacy_uuid("user", user_name)
        for players in GROUPS.values()
        for user_name in players
    }
    group_ids = {
        group_name: deterministic_legacy_uuid("group", group_name)
        for group_name in GROUPS
        if group_name != omit_group
    }
    session.add_all(
        User(
            id=user_id,
            display_name=user_name,
            timezone="UTC",
            created_at=FIXED_TIMESTAMP,
            updated_at=FIXED_TIMESTAMP,
        )
        for user_name, user_id in user_ids.items()
    )
    session.add_all(
        Group(
            id=group_id,
            name=group_name,
            timezone="UTC",
            created_at=FIXED_TIMESTAMP,
            updated_at=FIXED_TIMESTAMP,
        )
        for group_name, group_id in group_ids.items()
    )
    session.flush()
    session.add_all(
        GroupMembership(
            group_id=group_ids[group_name],
            user_id=user_ids[user_name],
            role=(
                MembershipRole.OWNER
                if OWNER_BY_GROUP[group_name] == user_name
                else MembershipRole.MEMBER
            ),
            display_order=display_order,
            joined_at=FIXED_TIMESTAMP,
        )
        for group_name, players in GROUPS.items()
        if group_name in group_ids
        for display_order, user_name in enumerate(players)
    )
    for user_name, day, status in availability or []:
        session.add(
            Availability(
                user_id=user_ids[user_name],
                day=day,
                status=status,
                updated_at=FIXED_TIMESTAMP,
            )
        )
    session.commit()


def runtime_settings(
    database_url: str,
    tmp_path: Path,
    *,
    mutations_enabled: bool = True,
) -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="test",
        LOG_LEVEL="CRITICAL",
        DATABASE_PATH=tmp_path / "unused-legacy-oracle.db",
        DATABASE_URL=database_url,
        MUTATIONS_ENABLED=mutations_enabled,
        CORS_ALLOWED_ORIGINS=["http://testserver"],
    )


def build_application(
    database_url: str,
    tmp_path: Path,
    *,
    mutations_enabled: bool = True,
) -> tuple[FastAPI, DatabaseRuntime]:
    runtime = create_database_runtime(database_url)
    application = create_app(
        runtime_settings(
            database_url,
            tmp_path,
            mutations_enabled=mutations_enabled,
        ),
        runtime,
    )
    return application, runtime


def post_availability(
    client: TestClient,
    *,
    group: str,
    user: str,
    day: str,
    status: str | None,
):
    return client.post(
        "/availability",
        json={"group": group, "user": user, "date": day, "status": status},
    )


def normalize_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(
        rows,
        key=lambda row: (
            row["group_name"],
            row["user_name"],
            row["date"],
            row["status"],
        ),
    )


def availability_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.scalar(sa.select(sa.func.count()).select_from(Availability))
        )


def test_startup_accepts_exact_head_and_legacy_dataset(
    tmp_path: Path,
    postgres_database_url: str,
    db_session: Session,
) -> None:
    seed_legacy_dataset(db_session)
    application, runtime = build_application(postgres_database_url, tmp_path)

    with TestClient(application) as client:
        assert client.get("/groups").json() == EXPECTED_GROUPS
        assert application.state.database_runtime is runtime


def test_explicit_test_runtime_does_not_require_database_url_setting(
    tmp_path: Path,
    postgres_database_url: str,
    db_session: Session,
) -> None:
    seed_legacy_dataset(db_session)
    runtime = create_database_runtime(postgres_database_url)
    application = create_app(
        Settings(
            _env_file=None,
            APP_ENV="test",
            LOG_LEVEL="CRITICAL",
            DATABASE_PATH=tmp_path / "unused-legacy-oracle.db",
            DATABASE_URL=None,
            CORS_ALLOWED_ORIGINS=["http://testserver"],
        ),
        runtime,
    )

    with TestClient(application) as client:
        assert client.get("/test-health").json() == {"status": "ok"}


def test_startup_rejects_wrong_revision_without_leaking_password(
    tmp_path: Path,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
) -> None:
    seed_legacy_dataset(db_session)
    with postgres_engine.begin() as connection:
        connection.execute(
            sa.text("UPDATE alembic_version SET version_num = 'unexpected_revision'")
        )
    application, _ = build_application(postgres_database_url, tmp_path)
    password = sa.engine.make_url(postgres_database_url).password

    try:
        with pytest.raises(DatabaseReadinessError, match="expected") as error:
            with TestClient(application):
                pass
        assert password is not None
        assert password not in str(error.value)
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "UPDATE alembic_version "
                    "SET version_num = '0001_phase_1_domain_schema'"
                )
            )


def test_startup_rejects_missing_expected_group(
    tmp_path: Path,
    postgres_database_url: str,
    db_session: Session,
) -> None:
    seed_legacy_dataset(db_session, omit_group="1D6")
    application, _ = build_application(postgres_database_url, tmp_path)

    with pytest.raises(compatibility.CompatibilityDatasetError, match="missing"):
        with TestClient(application):
            pass


def test_startup_rejects_ambiguous_expected_group_name(
    tmp_path: Path,
    postgres_database_url: str,
    db_session: Session,
) -> None:
    seed_legacy_dataset(db_session)
    db_session.add(Group(name="Green flag", timezone="UTC"))
    db_session.commit()
    application, _ = build_application(postgres_database_url, tmp_path)

    with pytest.raises(compatibility.CompatibilityDatasetError, match="ambiguous"):
        with TestClient(application):
            pass


def test_groups_and_unknown_group_month_preserve_exact_contract(
    tmp_path: Path,
    postgres_database_url: str,
    db_session: Session,
) -> None:
    seed_legacy_dataset(db_session)
    application, runtime = build_application(postgres_database_url, tmp_path)
    commit_events: list[None] = []

    def record_commit(connection: sa.Connection) -> None:
        del connection
        commit_events.append(None)

    with TestClient(application) as client:
        sa.event.listen(runtime.engine, "commit", record_commit)
        try:
            groups = client.get("/groups")
            unknown = client.get("/availability/Unknown/2026/1")
        finally:
            sa.event.remove(runtime.engine, "commit", record_commit)

    assert groups.status_code == 200
    assert groups.json() == EXPECTED_GROUPS
    assert unknown.status_code == 200
    assert unknown.json() == []
    assert commit_events == []


def test_month_read_translates_all_statuses_and_projects_shared_users(
    tmp_path: Path,
    postgres_database_url: str,
    db_session: Session,
) -> None:
    seed_legacy_dataset(
        db_session,
        availability=[
            ("Quentin", date(2026, 1, 1), AvailabilityStatus.AVAILABLE),
            ("Dembe", date(2026, 1, 2), AvailabilityStatus.MAYBE),
            ("Ulrich", date(2026, 1, 3), AvailabilityStatus.UNAVAILABLE),
            ("Quentin", date(2026, 2, 1), AvailabilityStatus.MAYBE),
        ],
    )
    application, _ = build_application(postgres_database_url, tmp_path)

    with TestClient(application) as client:
        green_rows = normalize_rows(
            client.get("/availability/Green flag/2026/1").json()
        )
        shared_rows = {
            group: client.get(f"/availability/{group}/2026/1").json()
            for group in GROUPS
        }

    assert {(row["user_name"], row["status"]) for row in green_rows} == {
        ("Quentin", "Available"),
        ("Dembe", "Maybe"),
        ("Ulrich", "No"),
    }
    assert all(row["date"].startswith("2026-01-") for row in green_rows)
    assert all("Unavailable" not in row["status"] for row in green_rows)
    assert all(
        any(row["user_name"] == "Dembe" for row in rows)
        for rows in shared_rows.values()
    )


def test_write_cycle_upserts_timestamp_and_clears_global_fact(
    tmp_path: Path,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
) -> None:
    seed_legacy_dataset(db_session)
    application, _ = build_application(postgres_database_url, tmp_path)

    with TestClient(application) as client:
        for status in ("Available", "Maybe", "No"):
            response = post_availability(
                client,
                group="Green flag",
                user="Ulrich",
                day="2026-05-09",
                status=status,
            )
            assert response.status_code == 200
            assert response.json() == {"status": "success", "new_state": status}

            rows = client.get("/availability/Green flag/2026/5").json()
            assert rows == [
                {
                    "group_name": "Green flag",
                    "user_name": "Ulrich",
                    "date": "2026-05-09",
                    "status": status,
                }
            ]

            if status == "Available":
                with Session(postgres_engine) as session, session.begin():
                    record = session.scalar(sa.select(Availability))
                    assert record is not None
                    record.updated_at = datetime(2000, 1, 1, tzinfo=timezone.utc)

        with Session(postgres_engine) as session:
            updated_at = session.scalar(sa.select(Availability.updated_at))
            assert updated_at is not None
            assert updated_at.year > 2000

        clear = post_availability(
            client,
            group="Green flag",
            user="Ulrich",
            day="2026-05-09",
            status=None,
        )
        assert clear.status_code == 200
        assert clear.json() == {"status": "success", "new_state": None}
        assert client.get("/availability/Green flag/2026/5").json() == []

    assert availability_count(postgres_engine) == 0


def test_shared_user_fan_out_is_idempotent_and_uses_one_global_key(
    tmp_path: Path,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
) -> None:
    seed_legacy_dataset(db_session)
    application, _ = build_application(postgres_database_url, tmp_path)

    with TestClient(application) as client:
        for group in GROUPS:
            response = post_availability(
                client,
                group=group,
                user="Dembe",
                day="2026-06-14",
                status="Available",
            )
            assert response.status_code == 200
        assert availability_count(postgres_engine) == 1

        for group in GROUPS:
            assert client.get(f"/availability/{group}/2026/6").json() == [
                {
                    "group_name": group,
                    "user_name": "Dembe",
                    "date": "2026-06-14",
                    "status": "Available",
                }
            ]

        post_availability(
            client,
            group="Underdark",
            user="Dembe",
            day="2026-06-14",
            status=None,
        )
        assert all(
            client.get(f"/availability/{group}/2026/6").json() == [] for group in GROUPS
        )


def test_noncanonical_status_is_rejected_with_422(
    tmp_path: Path,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
) -> None:
    seed_legacy_dataset(db_session)
    application, _ = build_application(postgres_database_url, tmp_path)

    with TestClient(application) as client:
        response = post_availability(
            client,
            group="Green flag",
            user="Quentin",
            day="2026-07-01",
            status="definitely-not-valid",
        )

    assert response.status_code == 422
    assert availability_count(postgres_engine) == 0


@pytest.mark.parametrize(
    ("group", "user", "expected_detail"),
    [
        ("Unknown", "Quentin", "Unknown group"),
        ("Green flag", "Unknown", "Unknown user"),
        ("1D6", "Quentin", "User is not a member"),
    ],
)
def test_unknown_or_nonmember_writes_are_rejected_with_422(
    tmp_path: Path,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
    group: str,
    user: str,
    expected_detail: str,
) -> None:
    seed_legacy_dataset(db_session)
    application, _ = build_application(postgres_database_url, tmp_path)

    with TestClient(application) as client:
        response = post_availability(
            client,
            group=group,
            user=user,
            day="2026-07-02",
            status="Available",
        )

    assert response.status_code == 422
    assert expected_detail in response.json()["detail"]
    assert availability_count(postgres_engine) == 0


def test_ambiguous_write_identities_are_rejected_with_422(
    tmp_path: Path,
    postgres_database_url: str,
    db_session: Session,
) -> None:
    seed_legacy_dataset(db_session)
    db_session.add_all(
        [
            User(id=uuid.uuid4(), display_name="Quentin", timezone="UTC"),
            Group(id=uuid.uuid4(), name="Other", timezone="UTC"),
            Group(id=uuid.uuid4(), name="Other", timezone="UTC"),
        ]
    )
    db_session.commit()
    application, _ = build_application(postgres_database_url, tmp_path)

    with TestClient(application) as client:
        ambiguous_user = post_availability(
            client,
            group="Green flag",
            user="Quentin",
            day="2026-07-03",
            status="Available",
        )
        ambiguous_group = post_availability(
            client,
            group="Other",
            user="Dembe",
            day="2026-07-03",
            status="Available",
        )

    assert ambiguous_user.status_code == 422
    assert ambiguous_group.status_code == 422


def test_admin_range_is_inclusive_and_expands_every_membership(
    tmp_path: Path,
    postgres_database_url: str,
    db_session: Session,
) -> None:
    seed_legacy_dataset(
        db_session,
        availability=[
            ("Dembe", date(2026, 8, 10), AvailabilityStatus.AVAILABLE),
            ("Quentin", date(2026, 8, 20), AvailabilityStatus.MAYBE),
            ("Ulrich", date(2026, 8, 21), AvailabilityStatus.UNAVAILABLE),
        ],
    )
    application, _ = build_application(postgres_database_url, tmp_path)

    with TestClient(application) as client:
        response = client.get("/admin/all-availability?start=2026-08-10&end=2026-08-20")

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
    assert all(row["status"] in {"Available", "Maybe", "No"} for row in rows)


def test_health_is_exact_and_safe_in_read_only_mode(
    tmp_path: Path,
    postgres_database_url: str,
    db_session: Session,
) -> None:
    seed_legacy_dataset(db_session)
    application, _ = build_application(
        postgres_database_url,
        tmp_path,
        mutations_enabled=False,
    )

    with TestClient(application) as client:
        response = client.get("/test-health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "database" not in response.text.lower()


def test_mutations_disabled_blocks_post_before_adapter_and_writes_nothing(
    tmp_path: Path,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_legacy_dataset(db_session)

    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("disabled mode invoked the mutation adapter")

    monkeypatch.setattr(compatibility, "set_user_availability", forbidden)
    application, runtime = build_application(
        postgres_database_url,
        tmp_path,
        mutations_enabled=False,
    )
    begin_events: list[None] = []

    def record_begin(connection: sa.Connection) -> None:
        del connection
        begin_events.append(None)

    with TestClient(application) as client:
        sa.event.listen(runtime.engine, "begin", record_begin)
        try:
            response = post_availability(
                client,
                group="Green flag",
                user="Quentin",
                day="2026-09-01",
                status="Available",
            )
        finally:
            sa.event.remove(runtime.engine, "begin", record_begin)

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Availability mutations are temporarily disabled"
    }
    assert begin_events == []
    assert availability_count(postgres_engine) == 0


def test_mutations_enabled_permits_post(
    tmp_path: Path,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
) -> None:
    seed_legacy_dataset(db_session)
    application, runtime = build_application(postgres_database_url, tmp_path)
    commit_events: list[None] = []

    def record_commit(connection: sa.Connection) -> None:
        del connection
        commit_events.append(None)

    with TestClient(application) as client:
        sa.event.listen(runtime.engine, "commit", record_commit)
        try:
            response = post_availability(
                client,
                group="Green flag",
                user="Quentin",
                day="2026-09-02",
                status="Available",
            )
        finally:
            sa.event.remove(runtime.engine, "commit", record_commit)

    assert response.status_code == 200
    assert len(commit_events) == 1
    assert availability_count(postgres_engine) == 1


def test_startup_emits_one_safe_compatibility_warning(
    tmp_path: Path,
    postgres_database_url: str,
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    seed_legacy_dataset(db_session)
    runtime = create_database_runtime(postgres_database_url)
    application = create_app(
        Settings(
            _env_file=None,
            APP_ENV="test",
            LOG_LEVEL="WARNING",
            DATABASE_PATH=tmp_path / "unused-legacy-oracle.db",
            DATABASE_URL=postgres_database_url,
            MUTATIONS_ENABLED=False,
            CORS_ALLOWED_ORIGINS=["http://testserver"],
        ),
        runtime,
    )

    with caplog.at_level("WARNING", logger="backend.main"):
        with TestClient(application) as client:
            assert client.get("/test-health").status_code == 200
            assert client.get("/test-health").status_code == 200

    warnings = [
        record.getMessage()
        for record in caplog.records
        if "phase1_compatibility_mode_active" in record.getMessage()
    ]
    assert warnings == ["phase1_compatibility_mode_active mutations_enabled=False"]
    combined = "\n".join(warnings)
    assert "Quentin" not in combined
    assert "2026-" not in combined
    assert "postgresql" not in combined


def test_request_transaction_failure_rolls_back_and_returns_safe_error(
    tmp_path: Path,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_legacy_dataset(db_session)

    def injected_failure(session: Session) -> None:
        del session
        raise RuntimeError("synthetic failure with no database details")

    monkeypatch.setattr(
        compatibility,
        "_after_availability_mutation",
        injected_failure,
    )
    application, _ = build_application(postgres_database_url, tmp_path)

    with TestClient(application) as client:
        response = post_availability(
            client,
            group="Green flag",
            user="Quentin",
            day="2026-09-03",
            status="Available",
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Availability mutation could not be completed"}
    assert availability_count(postgres_engine) == 0


def test_two_apps_have_isolated_settings_engines_sessions_and_rows(
    tmp_path: Path,
    postgres_database_url: str,
    second_postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
) -> None:
    seed_legacy_dataset(db_session)
    second_seed_runtime = create_database_runtime(second_postgres_database_url)
    try:
        with Session(second_seed_runtime.engine) as second_session:
            seed_legacy_dataset(second_session)
    finally:
        second_seed_runtime.dispose()

    first_app, first_runtime = build_application(postgres_database_url, tmp_path)
    second_app, second_runtime = build_application(
        second_postgres_database_url,
        tmp_path,
    )

    with (
        TestClient(first_app) as first_client,
        TestClient(second_app) as second_client,
    ):
        response = post_availability(
            first_client,
            group="Green flag",
            user="Quentin",
            day="2026-10-01",
            status="Available",
        )
        assert response.status_code == 200
        assert len(first_client.get("/availability/Green flag/2026/10").json()) == 1
        assert second_client.get("/availability/Green flag/2026/10").json() == []
        assert first_app.state.settings is not second_app.state.settings
        assert first_runtime is not second_runtime
        assert first_runtime.engine is not second_runtime.engine
        assert first_runtime.engine.pool is not second_runtime.engine.pool
        assert first_runtime.session_factory is not second_runtime.session_factory

    assert availability_count(postgres_engine) == 1


def test_module_import_and_startup_never_create_schema_or_run_alembic(
    tmp_path: Path,
    postgres_database_url: str,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_legacy_dataset(db_session)
    application, _ = build_application(postgres_database_url, tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("runtime attempted schema or migration work")

    import backend.db as db_module
    import backend.main as main_module

    monkeypatch.setattr(db_module, "create_engine", forbidden)
    monkeypatch.setattr(sa.MetaData, "create_all", forbidden)
    monkeypatch.setattr(sa.MetaData, "drop_all", forbidden)
    monkeypatch.setattr(alembic_command, "upgrade", forbidden)
    monkeypatch.setattr(alembic_command, "downgrade", forbidden)

    importlib.reload(main_module)
    with TestClient(application) as client:
        assert client.get("/test-health").json() == {"status": "ok"}


def test_unreachable_startup_error_redacts_database_password(tmp_path: Path) -> None:
    password = "do-not-expose-this-password"
    database_url = (
        f"postgresql+psycopg://runtime:{password}@127.0.0.1:1/unreachable_synthetic"
    )
    application, _ = build_application(database_url, tmp_path)

    with pytest.raises(DatabaseReadinessError) as error:
        with TestClient(application):
            pass

    assert password not in str(error.value)
    assert "127.0.0.1" in str(error.value)


def test_synthetic_import_matches_sqlite_compatibility_projections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
    db_session: Session,
) -> None:
    del db_session
    prepared = prepare_plan(tmp_path, monkeypatch, postgres_database_url)
    source = Path(prepared["source"])
    source_before = file_evidence(source)
    assert (
        importer.main(apply_arguments(prepared, tmp_path / "compatibility-apply.json"))
        == importer.ExitCode.SUCCESS
    )
    application, _ = build_application(postgres_database_url, tmp_path)

    with TestClient(application) as client:
        assert client.get("/groups").json() == EXPECTED_GROUPS
        for month in (1, 2, 3):
            for group_name in GROUPS:
                sqlite_rows = database.get_group_month_availability(
                    group_name,
                    2026,
                    month,
                    source,
                )
                postgres_rows = client.get(
                    f"/availability/{group_name}/2026/{month}"
                ).json()
                assert normalize_rows(postgres_rows) == normalize_rows(
                    [dict(row) for row in sqlite_rows]
                )

        sqlite_admin = database.get_all_availability(
            "2026-01-01",
            "2026-03-03",
            source,
        )
        postgres_admin = client.get(
            "/admin/all-availability?start=2026-01-01&end=2026-03-03"
        ).json()
        assert normalize_rows(postgres_admin) == normalize_rows(
            [dict(row) for row in sqlite_admin]
        )
        assert all(row["status"] != "Unavailable" for row in postgres_admin)

    assert file_evidence(source) == source_before
