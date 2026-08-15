from __future__ import annotations

import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from backend.cli import import_legacy_sqlite as importer
from backend.models import User
from backend.tests.test_import_legacy_sqlite import (
    CANONICAL_ROWS,
    copy_synthetic_source,
    create_synthetic_source,
    file_evidence,
    plan_arguments,
    write_normalization_policy,
    write_owner_map,
)


def domain_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table_name: connection.scalar(sa.text(f"SELECT count(*) FROM {table_name}"))
            for table_name in importer.DOMAIN_TABLE_NAMES
        }


def prepare_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
    *,
    rows: list[tuple[object, object, object, object]] | None = None,
    normalization_policy: Path | None = None,
) -> dict[str, object]:
    source = create_synthetic_source(
        tmp_path / "synthetic-source.sqlite",
        CANONICAL_ROWS if rows is None else rows,
    )
    backup = copy_synthetic_source(source, tmp_path / "synthetic-backup.sqlite")
    owner_map = write_owner_map(tmp_path / "synthetic-owners.json")
    expected_sha256 = file_evidence(source)[3]
    monkeypatch.setenv("IMPORT_DESTINATION_URL", postgres_database_url)
    arguments = plan_arguments(
        source,
        backup,
        owner_map,
        tmp_path,
        expected_sha256,
        normalization_policy,
    )
    assert importer.main(arguments) == importer.ExitCode.SUCCESS
    return {
        "source": source,
        "backup": backup,
        "owner_map": owner_map,
        "expected_sha256": expected_sha256,
        "mapping": tmp_path / "identity-map.json",
        "plan": tmp_path / "import-plan.json",
        "plan_report": tmp_path / "plan-report.json",
        "normalization_policy": normalization_policy,
    }


def apply_arguments(
    prepared: dict[str, object],
    report: Path,
    *,
    include_apply: bool = True,
) -> list[str]:
    arguments = [
        "apply",
        "--source-sqlite",
        str(prepared["source"]),
        "--backup-sqlite",
        str(prepared["backup"]),
        "--destination-url-env",
        "IMPORT_DESTINATION_URL",
        "--owner-map",
        str(prepared["owner_map"]),
        "--mapping",
        str(prepared["mapping"]),
        "--approved-plan",
        str(prepared["plan"]),
        "--report-output",
        str(report),
        "--expected-source-sha256",
        str(prepared["expected_sha256"]),
    ]
    if include_apply:
        arguments.append("--apply")
    if prepared["normalization_policy"] is not None:
        arguments.extend(
            ["--normalization-policy", str(prepared["normalization_policy"])]
        )
    return arguments


def verify_arguments(prepared: dict[str, object], report: Path) -> list[str]:
    arguments = [
        "verify",
        "--source-sqlite",
        str(prepared["source"]),
        "--destination-url-env",
        "IMPORT_DESTINATION_URL",
        "--owner-map",
        str(prepared["owner_map"]),
        "--mapping",
        str(prepared["mapping"]),
        "--approved-plan",
        str(prepared["plan"]),
        "--report-output",
        str(report),
        "--expected-source-sha256",
        str(prepared["expected_sha256"]),
    ]
    if prepared["normalization_policy"] is not None:
        arguments.extend(
            ["--normalization-policy", str(prepared["normalization_policy"])]
        )
    return arguments


def test_plan_requires_exact_head_and_writes_no_domain_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
) -> None:
    del db_session
    before = domain_counts(postgres_engine)
    prepared = prepare_plan(tmp_path, monkeypatch, postgres_database_url)
    after = domain_counts(postgres_engine)

    assert before == after == {table: 0 for table in importer.DOMAIN_TABLE_NAMES}
    mapping = json.loads(Path(prepared["mapping"]).read_text(encoding="utf-8"))
    plan = json.loads(Path(prepared["plan"]).read_text(encoding="utf-8"))
    report = json.loads(Path(prepared["plan_report"]).read_text(encoding="utf-8"))
    assert plan["destination"]["alembic_revision"] == "0002_phase_2a_accounts"
    assert report["destination"]["classification"] == "empty"
    assert plan["expected_counts"] == {
        "users": 12,
        "groups": 3,
        "group_memberships": 16,
        "availability": 3,
    }
    assert len(mapping["users"]) == 12
    assert len(mapping["groups"]) == 3


def test_destination_revision_mismatch_is_rejected_before_domain_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
) -> None:
    del db_session
    source = create_synthetic_source(tmp_path / "source.sqlite")
    backup = copy_synthetic_source(source, tmp_path / "backup.sqlite")
    owner_map = write_owner_map(tmp_path / "owners.json")
    monkeypatch.setenv("IMPORT_DESTINATION_URL", postgres_database_url)
    with postgres_engine.begin() as connection:
        connection.execute(
            sa.text("UPDATE alembic_version SET version_num = 'unexpected_revision'")
        )
    try:
        result = importer.main(
            plan_arguments(
                source,
                backup,
                owner_map,
                tmp_path,
                file_evidence(source)[3],
            )
        )
        assert result == importer.ExitCode.COMMAND_OR_VALIDATION_ERROR
        assert domain_counts(postgres_engine) == {
            table: 0 for table in importer.DOMAIN_TABLE_NAMES
        }
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "UPDATE alembic_version "
                    "SET version_num = '0002_phase_2a_accounts'"
                )
            )


def test_apply_verify_and_immediate_rerun_are_exact_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
) -> None:
    del db_session
    prepared = prepare_plan(tmp_path, monkeypatch, postgres_database_url)
    source_before = file_evidence(Path(prepared["source"]))
    backup_before = file_evidence(Path(prepared["backup"]))

    first_report = tmp_path / "apply-report.json"
    result = importer.main(apply_arguments(prepared, first_report))
    assert result == importer.ExitCode.SUCCESS, first_report.read_text(encoding="utf-8")
    first = json.loads(first_report.read_text(encoding="utf-8"))
    assert first["transaction_outcome"] == "applied"
    assert domain_counts(postgres_engine) == {
        "users": 12,
        "groups": 3,
        "group_memberships": 16,
        "availability": 3,
    }

    verification_report = tmp_path / "verification-report.json"
    assert (
        importer.main(verify_arguments(prepared, verification_report))
        == importer.ExitCode.SUCCESS
    )
    verification = json.loads(verification_report.read_text(encoding="utf-8"))
    assert verification["transaction_outcome"] == "verified"
    assert verification["verification"]["verification_mismatch_count"] == 0

    def fail_if_rerun_writes(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("exact rerun attempted domain writes")

    monkeypatch.setattr(importer, "_insert_plan_rows", fail_if_rerun_writes)
    rerun_report = tmp_path / "rerun-report.json"
    assert (
        importer.main(apply_arguments(prepared, rerun_report))
        == importer.ExitCode.SUCCESS
    )
    rerun = json.loads(rerun_report.read_text(encoding="utf-8"))
    assert rerun["transaction_outcome"] == "already_applied"
    assert all(value == 0 for value in rerun["imported_counts"].values())
    assert rerun["matched_counts"] == rerun["planned_counts"]
    assert file_evidence(Path(prepared["source"])) == source_before
    assert file_evidence(Path(prepared["backup"])) == backup_before


def test_normalization_policy_plan_apply_verify_is_exact_and_auditable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
) -> None:
    del db_session
    rows = [
        ("Legacy Admin", "Legacy Operator", "2026-01-01", "Available"),
        ("Legacy Dice", "Romane", "2026-01-02", "Available"),
        ("1D6", "Romane", "2026-01-02", "Maybe"),
        ("Green flag", "Legacy Quentin", "2026-01-03", "Available"),
        ("Green flag", "Quentin", "2026-01-03", "No"),
        ("Green flag", "Legacy Quentin", "2026-01-04", "Maybe"),
        ("Green flag", "Quentin", "2026-01-05", "Available"),
        ("Underdark", "Quentin", "2026-01-05", "Available"),
    ]
    policy_path = write_normalization_policy(
        tmp_path / "synthetic-policy.json",
        ignored_groups=["Legacy Admin"],
        group_aliases={"Legacy Dice": "1D6"},
        user_aliases={"Legacy Quentin": "Quentin"},
    )
    prepared = prepare_plan(
        tmp_path,
        monkeypatch,
        postgres_database_url,
        rows=rows,
        normalization_policy=policy_path,
    )
    source_before = file_evidence(Path(prepared["source"]))
    backup_before = file_evidence(Path(prepared["backup"]))
    plan = json.loads(Path(prepared["plan"]).read_text(encoding="utf-8"))

    assert plan["expected_counts"]["availability"] == 4
    assert plan["source"]["normalization"]["ignored_row_count"] == 1
    assert (
        plan["source"]["normalization"][
            "conflicts_resolved_by_canonical_user_precedence_count"
        ]
        == 1
    )
    assert (
        plan["source"]["normalization"][
            "conflicts_resolved_by_canonical_group_precedence_count"
        ]
        == 1
    )
    assert plan["source"]["normalization"]["remaining_unresolved_conflict_count"] == 0
    assert plan["normalization_policy"]["canonical_sha256"]
    assert plan["normalization_policy"]["file_sha256"]

    apply_report = tmp_path / "normalized-apply.json"
    assert (
        importer.main(apply_arguments(prepared, apply_report))
        == importer.ExitCode.SUCCESS
    )
    verify_report = tmp_path / "normalized-verify.json"
    assert (
        importer.main(verify_arguments(prepared, verify_report))
        == importer.ExitCode.SUCCESS
    )
    assert domain_counts(postgres_engine) == {
        "users": 12,
        "groups": 3,
        "group_memberships": 16,
        "availability": 4,
    }
    assert file_evidence(Path(prepared["source"])) == source_before
    assert file_evidence(Path(prepared["backup"])) == backup_before


def test_imported_rows_preserve_explicit_owners_order_and_plan_timestamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
) -> None:
    del db_session
    prepared = prepare_plan(tmp_path, monkeypatch, postgres_database_url)
    assert (
        importer.main(apply_arguments(prepared, tmp_path / "apply.json"))
        == importer.ExitCode.SUCCESS
    )
    plan = json.loads(Path(prepared["plan"]).read_text(encoding="utf-8"))
    with postgres_engine.connect() as connection:
        snapshot = importer._destination_snapshot(connection)
    assert snapshot == plan["rows"]

    users = {row["id"]: row["display_name"] for row in snapshot["users"]}
    groups = {row["id"]: row["name"] for row in snapshot["groups"]}
    memberships = sorted(
        (
            groups[row["group_id"]],
            row["display_order"],
            users[row["user_id"]],
            row["role"],
        )
        for row in snapshot["group_memberships"]
    )
    assert ("Green flag", 0, "Quentin", "owner") in memberships
    assert ("1D6", 0, "Gaelle", "owner") in memberships
    assert ("Underdark", 0, "Dembe", "owner") in memberships
    assert all(
        row["created_at"] == plan["imported_at"]
        and row["updated_at"] == plan["imported_at"]
        for row in snapshot["users"]
    )


def test_forced_mid_import_failure_rolls_back_every_domain_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
) -> None:
    del db_session
    prepared = prepare_plan(tmp_path, monkeypatch, postgres_database_url)

    def fail_after_groups(category: str, connection: Connection) -> None:
        del connection
        if category == "groups":
            raise RuntimeError("injected synthetic failure")

    monkeypatch.setattr(importer, "_after_category_flushed", fail_after_groups)
    assert (
        importer.main(apply_arguments(prepared, tmp_path / "failed-apply.json"))
        == importer.ExitCode.DATABASE_WRITE_FAILURE
    )
    assert domain_counts(postgres_engine) == {
        table: 0 for table in importer.DOMAIN_TABLE_NAMES
    }


def test_invalid_artifact_hash_and_missing_apply_switch_fail_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
) -> None:
    del db_session
    prepared = prepare_plan(tmp_path, monkeypatch, postgres_database_url)
    assert (
        importer.main(
            apply_arguments(
                prepared,
                tmp_path / "without-switch.json",
                include_apply=False,
            )
        )
        == importer.ExitCode.COMMAND_OR_VALIDATION_ERROR
    )

    mapping_path = Path(prepared["mapping"])
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    mapping["namespace"] = str(uuid_from_int(1))
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
    assert (
        importer.main(apply_arguments(prepared, tmp_path / "bad-hash.json"))
        == importer.ExitCode.COMMAND_OR_VALIDATION_ERROR
    )
    assert domain_counts(postgres_engine) == {
        table: 0 for table in importer.DOMAIN_TABLE_NAMES
    }


def uuid_from_int(value: int) -> str:
    return f"00000000-0000-0000-0000-{value:012d}"


@pytest.mark.parametrize("destination_state", ["partial", "unrelated", "differing"])
def test_nonmatching_nonempty_destinations_are_rejected_without_merge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
    destination_state: str,
) -> None:
    del db_session
    prepared = prepare_plan(tmp_path, monkeypatch, postgres_database_url)
    if destination_state == "partial":
        plan = json.loads(Path(prepared["plan"]).read_text(encoding="utf-8"))
        row = plan["rows"]["users"][0]
        with postgres_engine.begin() as connection:
            connection.execute(
                sa.insert(User.__table__),
                importer._database_rows("users", [row]),
            )
    elif destination_state == "unrelated":
        with Session(postgres_engine) as session, session.begin():
            session.add(User(display_name="Synthetic unrelated user"))
    else:
        assert (
            importer.main(apply_arguments(prepared, tmp_path / "initial.json"))
            == importer.ExitCode.SUCCESS
        )
        with postgres_engine.begin() as connection:
            connection.execute(sa.update(User).values(timezone="Europe/Paris"))

    before = domain_counts(postgres_engine)
    assert (
        importer.main(apply_arguments(prepared, tmp_path / "unsafe.json"))
        == importer.ExitCode.UNSAFE_DESTINATION
    )
    assert domain_counts(postgres_engine) == before
    report = json.loads((tmp_path / "unsafe.json").read_text(encoding="utf-8"))
    assert report["destination_comparison"]["total_mismatch_count"] > 0


def test_verify_mismatch_exits_six_and_reports_complete_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
) -> None:
    del db_session
    prepared = prepare_plan(tmp_path, monkeypatch, postgres_database_url)
    assert (
        importer.main(apply_arguments(prepared, tmp_path / "apply.json"))
        == importer.ExitCode.SUCCESS
    )
    with postgres_engine.begin() as connection:
        connection.execute(sa.update(User).values(display_name="Synthetic mismatch"))

    report_path = tmp_path / "mismatch.json"
    assert (
        importer.main(verify_arguments(prepared, report_path))
        == importer.ExitCode.VERIFICATION_FAILURE
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["verification"]["verification_mismatch_count"] > 0
    assert report["verification"]["tables"]["users"]["mismatch_count"] > 0


def test_apply_acquires_stable_transaction_advisory_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
    db_session: Session,
) -> None:
    del db_session
    prepared = prepare_plan(tmp_path, monkeypatch, postgres_database_url)
    real_lock = importer._acquire_advisory_lock
    observed: list[int] = []

    def record_lock(connection: Connection) -> None:
        observed.append(importer.IMPORT_ADVISORY_LOCK_KEY)
        real_lock(connection)

    monkeypatch.setattr(importer, "_acquire_advisory_lock", record_lock)
    assert (
        importer.main(apply_arguments(prepared, tmp_path / "apply.json"))
        == importer.ExitCode.SUCCESS
    )
    assert observed == [importer.IMPORT_ADVISORY_LOCK_KEY]


def test_committed_artifact_failure_recovers_as_exact_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
    postgres_engine: Engine,
    db_session: Session,
) -> None:
    del db_session
    prepared = prepare_plan(tmp_path, monkeypatch, postgres_database_url)
    real_writer = importer._atomic_write_json

    with monkeypatch.context() as patch_context:
        patch_context.setattr(
            importer,
            "_atomic_write_json",
            lambda path, document: (_ for _ in ()).throw(
                importer.ImporterError("injected artifact publication failure")
            ),
        )
        assert (
            importer.main(apply_arguments(prepared, tmp_path / "missing-report.json"))
            == importer.ExitCode.VERIFICATION_FAILURE
        )

    assert domain_counts(postgres_engine) == {
        "users": 12,
        "groups": 3,
        "group_memberships": 16,
        "availability": 3,
    }
    regenerated = tmp_path / "regenerated-report.json"
    monkeypatch.setattr(importer, "_atomic_write_json", real_writer)
    assert (
        importer.main(apply_arguments(prepared, regenerated))
        == importer.ExitCode.SUCCESS
    )
    assert (
        json.loads(regenerated.read_text(encoding="utf-8"))["transaction_outcome"]
        == "already_applied"
    )


def test_destination_url_is_redacted_in_all_artifacts_and_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
    db_session: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del db_session
    prepared = prepare_plan(tmp_path, monkeypatch, postgres_database_url)
    report = tmp_path / "apply.json"
    assert importer.main(apply_arguments(prepared, report)) == importer.ExitCode.SUCCESS
    captured = capsys.readouterr()
    password = sa.engine.make_url(postgres_database_url).password
    assert password
    for candidate in [
        captured.out,
        captured.err,
        *[path.read_text(encoding="utf-8") for path in tmp_path.glob("*.json")],
    ]:
        assert password not in candidate


def test_importer_never_invokes_schema_creation_or_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
    db_session: Session,
) -> None:
    del db_session
    prepared = prepare_plan(tmp_path, monkeypatch, postgres_database_url)

    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("schema management was invoked by importer")

    monkeypatch.setattr(sa.MetaData, "create_all", forbidden)
    monkeypatch.setattr(sa.MetaData, "drop_all", forbidden)
    assert (
        importer.main(apply_arguments(prepared, tmp_path / "apply.json"))
        == importer.ExitCode.SUCCESS
    )
