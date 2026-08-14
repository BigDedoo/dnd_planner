from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import uuid
from pathlib import Path

import pytest

from backend import database
from backend.cli import import_legacy_sqlite as importer
from backend.legacy_contract import (
    DOMAIN_TO_LEGACY_STATUS,
    GROUPS,
    LEGACY_IMPORT_NAMESPACE,
    LEGACY_TO_DOMAIN_STATUS,
    LEGACY_USERS,
    STATUS_MAP_VERSION,
    canonical_legacy_identity,
    deterministic_legacy_uuid,
)

CANONICAL_ROWS = [
    ("Green flag", "Quentin", "2026-01-01", "Available"),
    ("Underdark", "Quentin", "2026-01-01", "Available"),
    ("1D6", "Dembe", "2026-02-02", "Maybe"),
    ("Green flag", "Ulrich", "2026-03-03", "No"),
]

EXPECTED_GROUPS = {
    "Green flag": ("Quentin", "Arnaud", "Ulrich", "Daerrus", "Dembe"),
    "1D6": ("Gaelle", "Rico", "Yoann", "Romane", "Victor", "Dembe"),
    "Underdark": ("Dembe", "Arnaud", "Quentin", "Martin", "Baptiste"),
}


def create_synthetic_source(
    path: Path,
    rows: list[tuple[object, object, object, object]] | None = None,
    *,
    create_sql: str | None = None,
) -> Path:
    schema = (
        create_sql
        or """
        CREATE TABLE availability (
            group_name TEXT,
            user_name TEXT,
            date TEXT,
            status TEXT,
            PRIMARY KEY (group_name, user_name, date)
        )
    """
    )
    with sqlite3.connect(path) as connection:
        connection.execute(schema)
        if rows:
            connection.executemany(
                "INSERT INTO availability (group_name, user_name, date, status) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )
    return path


def create_missing_table_source(path: Path) -> Path:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
    return path


def copy_synthetic_source(source: Path, backup: Path) -> Path:
    shutil.copy2(source, backup)
    return backup


def write_owner_map(
    path: Path,
    groups: dict[str, object] | None = None,
    *,
    version: int = 1,
) -> Path:
    owners = groups or {
        "Green flag": "Quentin",
        "1D6": "Gaelle",
        "Underdark": "Dembe",
    }
    path.write_text(
        json.dumps({"version": version, "groups": owners}),
        encoding="utf-8",
    )
    return path


def write_normalization_policy(
    path: Path,
    *,
    ignored_groups: list[str] | None = None,
    group_aliases: dict[str, str] | None = None,
    user_aliases: dict[str, str] | None = None,
    prefer_canonical_on_conflict: bool = True,
    version: int = 1,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "version": version,
                "ignored_groups": ignored_groups or [],
                "group_aliases": group_aliases or {},
                "user_aliases": user_aliases or {},
                "prefer_canonical_on_conflict": prefer_canonical_on_conflict,
            }
        ),
        encoding="utf-8",
    )
    return path


def file_evidence(path: Path) -> tuple[bytes, int, int, str]:
    contents = path.read_bytes()
    metadata = path.stat()
    return (
        contents,
        metadata.st_size,
        metadata.st_mtime_ns,
        hashlib.sha256(contents).hexdigest(),
    )


def test_git_evidence_uses_validated_container_build_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "0123456789abcdef0123456789abcdef01234567"
    build_commit = tmp_path / ".dnd-planner-build-commit"
    build_commit.write_text(f"{commit}\n", encoding="ascii")

    def missing_git(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise FileNotFoundError

    monkeypatch.setattr(importer, "BUILD_COMMIT_PATH", build_commit)
    monkeypatch.setattr(importer.subprocess, "run", missing_git)

    assert importer._git_evidence() == {
        "commit": commit,
        "working_tree_dirty": False,
    }


def inspect_arguments(
    source: Path,
    report: Path,
    normalization_policy: Path | None = None,
) -> list[str]:
    arguments = [
        "inspect",
        "--source-sqlite",
        str(source),
        "--report-output",
        str(report),
    ]
    if normalization_policy is not None:
        arguments.extend(["--normalization-policy", str(normalization_policy)])
    return arguments


def plan_arguments(
    source: Path,
    backup: Path,
    owner_map: Path,
    output_directory: Path,
    expected_sha256: str,
    normalization_policy: Path | None = None,
) -> list[str]:
    arguments = [
        "plan",
        "--source-sqlite",
        str(source),
        "--backup-sqlite",
        str(backup),
        "--destination-url-env",
        "IMPORT_DESTINATION_URL",
        "--owner-map",
        str(owner_map),
        "--mapping-output",
        str(output_directory / "identity-map.json"),
        "--plan-output",
        str(output_directory / "import-plan.json"),
        "--report-output",
        str(output_directory / "plan-report.json"),
        "--expected-source-sha256",
        expected_sha256,
    ]
    if normalization_policy is not None:
        arguments.extend(["--normalization-policy", str(normalization_policy)])
    return arguments


def test_legacy_contract_parity_is_exact_and_authoritative() -> None:
    assert dict(GROUPS) == EXPECTED_GROUPS
    assert database.GROUPS is GROUPS
    assert LEGACY_USERS == (
        "Quentin",
        "Arnaud",
        "Ulrich",
        "Daerrus",
        "Dembe",
        "Gaelle",
        "Rico",
        "Yoann",
        "Romane",
        "Victor",
        "Martin",
        "Baptiste",
    )
    assert len(set(LEGACY_USERS)) == 12
    assert STATUS_MAP_VERSION == 1
    assert dict(LEGACY_TO_DOMAIN_STATUS) == {
        "Available": "available",
        "Maybe": "maybe",
        "No": "unavailable",
    }
    assert dict(DOMAIN_TO_LEGACY_STATUS) == {
        "available": "Available",
        "maybe": "Maybe",
        "unavailable": "No",
    }
    assert "Unavailable" not in LEGACY_TO_DOMAIN_STATUS


def test_uuidv5_identities_use_fixed_namespace_and_nfc_only() -> None:
    assert LEGACY_IMPORT_NAMESPACE == uuid.UUID("b47e7a21-6b6f-4c5d-a3d2-193b02d77d6f")
    canonical = canonical_legacy_identity("user", "Quentin")
    assert canonical == "user\0Quentin"
    assert deterministic_legacy_uuid("user", "Quentin") == uuid.uuid5(
        LEGACY_IMPORT_NAMESPACE,
        canonical,
    )
    assert deterministic_legacy_uuid(
        "group", "Green flag"
    ) != deterministic_legacy_uuid("user", "Green flag")
    assert deterministic_legacy_uuid("user", "Name") != deterministic_legacy_uuid(
        "user", "name"
    )


def test_distinct_unicode_values_with_one_nfc_key_are_rejected() -> None:
    with pytest.raises(importer.ImporterError, match="same NFC identity"):
        importer._identity_records("user", ("é", "e\u0301"))


@pytest.mark.parametrize("rows", [[], CANONICAL_ROWS])
def test_inspect_accepts_empty_and_canonical_synthetic_sources(
    tmp_path: Path,
    rows: list[tuple[object, object, object, object]],
) -> None:
    source = create_synthetic_source(tmp_path / "synthetic-source.sqlite", rows)
    report = tmp_path / "inspect-report.json"
    before = file_evidence(source)

    assert importer.main(inspect_arguments(source, report)) == importer.ExitCode.SUCCESS

    assert file_evidence(source) == before
    artifact = json.loads(report.read_text(encoding="utf-8"))
    assert artifact["artifact_type"] == "inspect_report"
    assert artifact["source"]["unchanged"] is True
    assert artifact["source"]["statistics"]["raw_row_count"] == len(rows)
    assert artifact["source"]["schema_errors"] == []
    assert artifact["source"]["validation_errors"] == []
    assert artifact["transaction_outcome"] == "inspected"
    assert not list(tmp_path.glob("*-journal"))
    assert not list(tmp_path.glob("*-wal"))
    assert not list(tmp_path.glob("*-shm"))


def test_shared_users_and_identical_logical_duplicates_are_reported_once(
    tmp_path: Path,
) -> None:
    source = create_synthetic_source(tmp_path / "shared.sqlite", CANONICAL_ROWS)
    inspection = importer.inspect_source(source)

    assert inspection["statistics"]["raw_row_count"] == 4
    assert inspection["statistics"]["distinct_logical_user_day_count"] == 3
    assert inspection["statistics"]["repeated_identical_logical_fact_count"] == 1
    assert inspection["conflicting_logical_facts"] == []
    assert len(inspection["logical_facts"]) == 3


def test_ignored_group_is_fully_audited_without_creating_a_canonical_user(
    tmp_path: Path,
) -> None:
    source = create_synthetic_source(
        tmp_path / "ignored.sqlite",
        [
            ("Legacy Admin", "Legacy Operator", "2026-01-01", "Available"),
            ("Green flag", "Quentin", "2026-01-02", "Maybe"),
        ],
    )
    policy_path = write_normalization_policy(
        tmp_path / "policy.json",
        ignored_groups=["Legacy Admin"],
    )
    report = tmp_path / "inspect.json"
    before = file_evidence(source)

    assert (
        importer.main(inspect_arguments(source, report, policy_path))
        == importer.ExitCode.SUCCESS
    )

    assert file_evidence(source) == before
    inspection = json.loads(report.read_text(encoding="utf-8"))["source"]
    normalization = inspection["normalization"]
    assert inspection["statistics"]["raw_row_count"] == 2
    assert normalization["ignored_row_count"] == 1
    assert normalization["ignored_rows_by_reason"] == {"explicit_policy_group": 1}
    assert normalization["ignored_rows_by_group"] == {"Legacy Admin": 1}
    assert normalization["canonical_users"] == ["Quentin"]
    assert "Legacy Operator" not in normalization["canonical_users"]
    assert inspection["logical_facts"] == [
        {
            "user_name": "Quentin",
            "day": "2026-01-02",
            "legacy_status": "Maybe",
            "status": "maybe",
        }
    ]
    ignored_decision = next(
        decision
        for decision in normalization["row_decisions"]
        if decision["disposition"] == "ignored_group"
    )
    assert ignored_decision["original_group"] == "Legacy Admin"
    assert ignored_decision["original_user"] == "Legacy Operator"
    assert ignored_decision["disposition"] == "ignored_group"


def test_alias_only_user_fact_is_preserved_under_canonical_identity_and_uuid(
    tmp_path: Path,
) -> None:
    source = create_synthetic_source(
        tmp_path / "user-alias.sqlite",
        [("Green flag", "Legacy Quentin", "2026-01-01", "Available")],
    )
    policy = importer._load_normalization_policy(
        write_normalization_policy(
            tmp_path / "policy.json",
            user_aliases={"Legacy Quentin": "Quentin"},
        )
    )
    inspection = importer.inspect_source(source, policy)
    state = importer._expected_import_state(
        list(inspection["logical_facts"]),
        {"Green flag": "Quentin", "1D6": "Gaelle", "Underdark": "Dembe"},
        "2026-01-01T00:00:00.000000Z",
    )

    assert inspection["logical_facts"] == [
        {
            "user_name": "Quentin",
            "day": "2026-01-01",
            "legacy_status": "Available",
            "status": "available",
        }
    ]
    quentin = next(
        identity
        for identity in state["user_identities"]
        if identity["source_value"] == "Quentin"
    )
    assert quentin["uuid"] == str(importer.deterministic_legacy_uuid("user", "Quentin"))
    assert all(
        identity["source_value"] != "Legacy Quentin"
        for identity in state["user_identities"]
    )


@pytest.mark.parametrize(
    ("alias_status", "canonical_status", "expected_status", "resolved_count"),
    [
        ("Available", "Available", "Available", 0),
        ("Available", "No", "No", 1),
        ("Maybe", "Available", "Available", 1),
    ],
)
def test_canonical_user_precedence_is_narrow_and_deterministic(
    tmp_path: Path,
    alias_status: str,
    canonical_status: str,
    expected_status: str,
    resolved_count: int,
) -> None:
    source = create_synthetic_source(
        tmp_path / "user-precedence.sqlite",
        [
            ("Green flag", "Legacy Quentin", "2026-01-01", alias_status),
            ("Green flag", "Quentin", "2026-01-01", canonical_status),
        ],
    )
    policy = importer._load_normalization_policy(
        write_normalization_policy(
            tmp_path / "policy.json",
            user_aliases={"Legacy Quentin": "Quentin"},
        )
    )

    inspection = importer.inspect_source(source, policy)

    assert len(inspection["logical_facts"]) == 1
    assert inspection["logical_facts"][0]["legacy_status"] == expected_status
    normalization = inspection["normalization"]
    assert (
        normalization["conflicts_resolved_by_canonical_user_precedence_count"]
        == resolved_count
    )
    alias_decision = next(
        decision
        for decision in normalization["row_decisions"]
        if decision["original_user"] == "Legacy Quentin"
    )
    assert alias_decision["disposition"] == "overridden_by_canonical_user"


@pytest.mark.parametrize(
    ("canonical_status", "expected_status", "resolved_count"),
    [
        (None, "Available", 0),
        ("Available", "Available", 0),
        ("Maybe", "Maybe", 1),
    ],
)
def test_canonical_group_precedence_preserves_alias_only_and_resolves_conflict(
    tmp_path: Path,
    canonical_status: str | None,
    expected_status: str,
    resolved_count: int,
) -> None:
    rows: list[tuple[object, object, object, object]] = [
        ("Legacy Dice", "Romane", "2026-02-01", "Available")
    ]
    if canonical_status is not None:
        rows.append(("1D6", "Romane", "2026-02-01", canonical_status))
    source = create_synthetic_source(tmp_path / "group-precedence.sqlite", rows)
    policy = importer._load_normalization_policy(
        write_normalization_policy(
            tmp_path / "policy.json",
            group_aliases={"Legacy Dice": "1D6"},
        )
    )

    inspection = importer.inspect_source(source, policy)

    assert len(inspection["logical_facts"]) == 1
    assert inspection["logical_facts"][0]["legacy_status"] == expected_status
    normalization = inspection["normalization"]
    assert (
        normalization["conflicts_resolved_by_canonical_group_precedence_count"]
        == resolved_count
    )
    alias_decision = next(
        decision
        for decision in normalization["row_decisions"]
        if decision["original_group"] == "Legacy Dice"
    )
    expected_disposition = (
        "contributes_to_logical_fact"
        if canonical_status is None
        else "overridden_by_canonical_group"
    )
    assert alias_decision["disposition"] == expected_disposition


def test_global_availability_remains_one_fact_across_multiple_groups(
    tmp_path: Path,
) -> None:
    source = create_synthetic_source(
        tmp_path / "global.sqlite",
        [
            ("Green flag", "Quentin", "2026-01-01", "Available"),
            ("Underdark", "Quentin", "2026-01-01", "Available"),
            ("Legacy Underground", "Quentin", "2026-01-01", "Available"),
        ],
    )
    policy = importer._load_normalization_policy(
        write_normalization_policy(
            tmp_path / "policy.json",
            group_aliases={"Legacy Underground": "Underdark"},
        )
    )

    inspection = importer.inspect_source(source, policy)

    assert len(inspection["logical_facts"]) == 1
    assert inspection["normalization"]["normalized_global_user_day_fact_count"] == 1
    assert inspection["normalization"]["normalized_counts_by_status"] == {
        "Available": 1
    }


def test_equally_canonical_conflict_still_fails_with_policy(tmp_path: Path) -> None:
    source = create_synthetic_source(
        tmp_path / "canonical-conflict.sqlite",
        [
            ("Green flag", "Quentin", "2026-01-01", "Available"),
            ("Underdark", "Quentin", "2026-01-01", "No"),
        ],
    )
    policy_path = write_normalization_policy(tmp_path / "policy.json")
    report = tmp_path / "inspect.json"

    assert (
        importer.main(inspect_arguments(source, report, policy_path))
        == importer.ExitCode.SOURCE_DATA_CONFLICT
    )
    source_report = json.loads(report.read_text(encoding="utf-8"))["source"]
    assert len(source_report["conflicting_logical_facts"]) == 1
    assert source_report["normalization"]["remaining_unresolved_conflict_count"] == 1


def test_disabling_canonical_preference_leaves_alias_conflict_unresolved(
    tmp_path: Path,
) -> None:
    source = create_synthetic_source(
        tmp_path / "disabled-precedence.sqlite",
        [
            ("Green flag", "Legacy Quentin", "2026-01-01", "Available"),
            ("Green flag", "Quentin", "2026-01-01", "No"),
        ],
    )
    policy = importer._load_normalization_policy(
        write_normalization_policy(
            tmp_path / "policy.json",
            user_aliases={"Legacy Quentin": "Quentin"},
            prefer_canonical_on_conflict=False,
        )
    )

    inspection = importer.inspect_source(source, policy)

    assert inspection["logical_facts"] == []
    assert len(inspection["conflicting_logical_facts"]) == 1
    assert (
        inspection["normalization"][
            "conflicts_resolved_by_canonical_user_precedence_count"
        ]
        == 0
    )


@pytest.mark.parametrize(
    ("row", "category"),
    [
        (
            ("Unknown", "Quentin", "2026-01-01", "Available"),
            "unknown_or_noncanonical_group",
        ),
        (
            ("Green flag", "Unknown", "2026-01-01", "Available"),
            "unknown_or_noncanonical_user",
        ),
        (
            ("Green flag", "Quentin", "2026-01-01", "Unavailable"),
            "unknown_or_noncanonical_status",
        ),
        (("Green flag", "Quentin", "not-a-date", "Available"), "malformed_date"),
    ],
)
def test_policy_does_not_relax_unaliased_identity_status_or_date_validation(
    tmp_path: Path,
    row: tuple[object, object, object, object],
    category: str,
) -> None:
    source = create_synthetic_source(tmp_path / "invalid.sqlite", [row])
    policy_path = write_normalization_policy(tmp_path / "policy.json")
    report = tmp_path / "inspect.json"

    assert (
        importer.main(inspect_arguments(source, report, policy_path))
        == importer.ExitCode.COMMAND_OR_VALIDATION_ERROR
    )
    categories = {
        error["category"]
        for error in json.loads(report.read_text(encoding="utf-8"))["source"][
            "validation_errors"
        ]
    }
    assert category in categories


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (
            {
                "version": 2,
                "ignored_groups": [],
                "group_aliases": {},
                "user_aliases": {},
                "prefer_canonical_on_conflict": True,
            },
            "version must be 1",
        ),
        (
            {
                "version": 1,
                "ignored_groups": [],
                "group_aliases": {"Legacy A": "Legacy B", "Legacy B": "Legacy A"},
                "user_aliases": {},
                "prefer_canonical_on_conflict": True,
            },
            "alias cycle",
        ),
        (
            {
                "version": 1,
                "ignored_groups": [],
                "group_aliases": {},
                "user_aliases": {"Legacy User": "Legacy User"},
                "prefer_canonical_on_conflict": True,
            },
            "self alias",
        ),
        (
            {
                "version": 1,
                "ignored_groups": [],
                "group_aliases": {"Legacy Group": "Unknown Group"},
                "user_aliases": {},
                "prefer_canonical_on_conflict": True,
            },
            "unknown canonical identity",
        ),
        (
            {
                "version": 1,
                "ignored_groups": [],
                "group_aliases": {},
                "user_aliases": {"Legacy User": "Unknown User"},
                "prefer_canonical_on_conflict": True,
            },
            "unknown canonical identity",
        ),
        (
            {
                "version": 1,
                "ignored_groups": ["1D6"],
                "group_aliases": {},
                "user_aliases": {},
                "prefer_canonical_on_conflict": True,
            },
            "may not ignore a canonical production group",
        ),
        (
            {
                "version": 1,
                "ignored_groups": ["Legacy Group"],
                "group_aliases": {"Legacy Group": "1D6"},
                "user_aliases": {},
                "prefer_canonical_on_conflict": True,
            },
            "ambiguous",
        ),
        (
            {
                "version": 1,
                "ignored_groups": "Legacy Group",
                "group_aliases": {},
                "user_aliases": {},
                "prefer_canonical_on_conflict": True,
            },
            "must be a JSON array",
        ),
        (
            {
                "version": 1,
                "ignored_groups": [],
                "group_aliases": {},
                "user_aliases": {},
                "prefer_canonical_on_conflict": "yes",
            },
            "must be boolean",
        ),
        (
            {
                "version": 1,
                "ignored_groups": [],
                "group_aliases": {},
                "user_aliases": {},
                "prefer_canonical_on_conflict": True,
                "unexpected": True,
            },
            "exactly the version 1 fields",
        ),
    ],
)
def test_invalid_normalization_policies_fail_closed(
    tmp_path: Path,
    document: dict[str, object],
    message: str,
) -> None:
    policy_path = tmp_path / "invalid-policy.json"
    policy_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(importer.ImporterError, match=message):
        importer._load_normalization_policy(policy_path)


def test_duplicate_policy_alias_definition_is_rejected(tmp_path: Path) -> None:
    policy_path = tmp_path / "duplicate-policy.json"
    policy_path.write_text(
        """{
          "version": 1,
          "ignored_groups": [],
          "group_aliases": {"Legacy Dice": "1D6", "Legacy Dice": "Underdark"},
          "user_aliases": {},
          "prefer_canonical_on_conflict": true
        }""",
        encoding="utf-8",
    )

    with pytest.raises(importer.ImporterError, match="duplicate key"):
        importer._load_normalization_policy(policy_path)


def test_policy_canonical_checksum_is_independent_of_json_order_and_formatting(
    tmp_path: Path,
) -> None:
    first_path = write_normalization_policy(
        tmp_path / "first-policy.json",
        ignored_groups=["Legacy Admin", "Legacy Archive"],
        group_aliases={"Legacy Underground": "Underdark", "Legacy Dice": "1D6"},
        user_aliases={"Legacy Arnaud": "Arnaud", "Legacy Quentin": "Quentin"},
    )
    second_path = tmp_path / "second-policy.json"
    second_path.write_text(
        json.dumps(
            {
                "user_aliases": {
                    "Legacy Quentin": "Quentin",
                    "Legacy Arnaud": "Arnaud",
                },
                "prefer_canonical_on_conflict": True,
                "group_aliases": {
                    "Legacy Dice": "1D6",
                    "Legacy Underground": "Underdark",
                },
                "ignored_groups": ["Legacy Archive", "Legacy Admin"],
                "version": 1,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    first = importer._load_normalization_policy(first_path)
    second = importer._load_normalization_policy(second_path)

    assert first.canonical_document() == second.canonical_document()
    assert first.canonical_sha256 == second.canonical_sha256
    assert first.file_sha256 != second.file_sha256


def test_changed_policy_invalidates_approved_artifact_evidence(
    tmp_path: Path,
) -> None:
    source = create_synthetic_source(tmp_path / "source.sqlite", CANONICAL_ROWS)
    backup = copy_synthetic_source(source, tmp_path / "backup.sqlite")
    owner_map = importer._load_owner_map(write_owner_map(tmp_path / "owners.json"))
    approved_policy = importer._load_normalization_policy(
        write_normalization_policy(
            tmp_path / "approved-policy.json",
            group_aliases={"Legacy Dice": "1D6"},
        )
    )
    inspection, backup_evidence = importer._validate_source_and_backup(
        source,
        backup,
        file_evidence(source)[3],
        approved_policy,
    )
    destination = importer.Destination(
        "IMPORT_DESTINATION_URL",
        "postgresql+psycopg://synthetic:password@127.0.0.1/synthetic",
    )
    imported_at = importer._utc_now()
    mapping, plan = importer._build_expected_artifacts(
        inspection,
        owner_map,
        imported_at,
        destination,
        "0001_phase_1_domain_schema",
        backup_evidence,
        approved_policy,
    )
    changed_policy = importer._load_normalization_policy(
        write_normalization_policy(
            tmp_path / "changed-policy.json",
            user_aliases={"Legacy Quentin": "Quentin"},
        )
    )
    changed_inspection = importer.inspect_source(source, changed_policy)
    changed_mapping, changed_plan = importer._build_expected_artifacts(
        changed_inspection,
        owner_map,
        imported_at,
        destination,
        "0001_phase_1_domain_schema",
        backup_evidence,
        changed_policy,
    )

    assert (
        mapping["normalization_policy"]["canonical_sha256"]
        == approved_policy.canonical_sha256
    )
    assert (
        plan["normalization_policy"]["canonical_sha256"]
        == approved_policy.canonical_sha256
    )
    assert approved_policy.canonical_sha256 != changed_policy.canonical_sha256
    assert mapping["content_sha256"] != changed_mapping["content_sha256"]
    assert plan["content_sha256"] != changed_plan["content_sha256"]
    with pytest.raises(importer.ImporterError, match="normalization"):
        importer._validate_artifacts_against_inputs(
            inspection=changed_inspection,
            backup_metadata=None,
            owner_map=owner_map,
            normalization_policy=changed_policy,
            mapping=mapping,
            mapping_file_checksum=importer._sha256_bytes(
                importer._json_file_bytes(mapping)
            ),
            plan=plan,
        )


def test_no_policy_preserves_exact_legacy_validation_and_artifact_shape(
    tmp_path: Path,
) -> None:
    rows = list(CANONICAL_ROWS)
    source = create_synthetic_source(tmp_path / "source.sqlite", rows)
    backup = copy_synthetic_source(source, tmp_path / "backup.sqlite")
    owner_map = importer._load_owner_map(write_owner_map(tmp_path / "owners.json"))

    assert importer._validate_source_rows(rows) == (
        importer._validate_source_rows_without_policy(rows)
    )
    inspection, backup_evidence = importer._validate_source_and_backup(
        source,
        backup,
        file_evidence(source)[3],
    )
    mapping, plan = importer._build_expected_artifacts(
        inspection,
        owner_map,
        importer._utc_now(),
        importer.Destination(
            "IMPORT_DESTINATION_URL",
            "postgresql+psycopg://synthetic:password@127.0.0.1/synthetic",
        ),
        "0001_phase_1_domain_schema",
        backup_evidence,
    )

    assert "normalization" not in inspection
    assert "normalization_policy" not in mapping
    assert "normalization_policy" not in plan
    assert "normalization" not in plan["source"]


def test_expected_state_canonicalizes_facts_for_exact_destination_verification(
    tmp_path: Path,
) -> None:
    source = create_synthetic_source(
        tmp_path / "canonical-order.sqlite", CANONICAL_ROWS
    )
    inspection = importer.inspect_source(source)
    state = importer._expected_import_state(
        list(inspection["logical_facts"]),
        {"Green flag": "Quentin", "1D6": "Gaelle", "Underdark": "Dembe"},
        "2026-01-01T00:00:00.000000Z",
    )
    plan = {
        "rows": state["rows"],
        "logical_facts": state["logical_facts"],
        "compatibility_projections": state["projections"],
        "checksums": state["checksums"],
    }

    assert state["logical_facts"] == importer._sort_rows(
        list(inspection["logical_facts"])
    )
    assert (
        importer._verify_snapshot(plan, state["rows"])["verification_mismatch_count"]
        == 0
    )


def test_conflicting_logical_facts_exit_three_and_list_every_coordinate(
    tmp_path: Path,
) -> None:
    source = create_synthetic_source(
        tmp_path / "conflict.sqlite",
        [
            ("Green flag", "Quentin", "2026-01-01", "Available"),
            ("Underdark", "Quentin", "2026-01-01", "No"),
        ],
    )
    report = tmp_path / "conflict-report.json"

    assert (
        importer.main(inspect_arguments(source, report))
        == importer.ExitCode.SOURCE_DATA_CONFLICT
    )
    artifact = json.loads(report.read_text(encoding="utf-8"))
    conflicts = artifact["source"]["conflicting_logical_facts"]
    assert len(conflicts) == 1
    assert conflicts[0]["statuses"] == ["Available", "No"]
    assert len(conflicts[0]["source_rows"]) == 2


@pytest.mark.parametrize(
    ("row", "category"),
    [
        (
            ("Unknown", "Quentin", "2026-01-01", "Available"),
            "unknown_or_noncanonical_group",
        ),
        (
            ("Green flag", "Unknown", "2026-01-01", "Available"),
            "unknown_or_noncanonical_user",
        ),
        (("1D6", "Quentin", "2026-01-01", "Available"), "user_not_in_group"),
        ((None, "Quentin", "2026-01-01", "Available"), "null_group_name"),
        ((" ", "Quentin", "2026-01-01", "Available"), "blank_group_name"),
        (("Green flag", None, "2026-01-01", "Available"), "null_user_name"),
        (("Green flag", " ", "2026-01-01", "Available"), "blank_user_name"),
        (("Green flag", "Quentin", None, "Available"), "null_date"),
        (("Green flag", "Quentin", "not-a-date", "Available"), "malformed_date"),
        (("Green flag", "Quentin", "20260101", "Available"), "noncanonical_date"),
    ],
)
def test_invalid_identity_and_date_categories_fail_closed(
    tmp_path: Path,
    row: tuple[object, object, object, object],
    category: str,
) -> None:
    source = create_synthetic_source(tmp_path / f"{category}.sqlite", [row])
    report = tmp_path / f"{category}.json"

    assert (
        importer.main(inspect_arguments(source, report))
        == importer.ExitCode.COMMAND_OR_VALIDATION_ERROR
    )
    categories = {
        error["category"]
        for error in json.loads(report.read_text(encoding="utf-8"))["source"][
            "validation_errors"
        ]
    }
    assert category in categories


@pytest.mark.parametrize(
    "invalid_status",
    [None, "", " ", "Unavailable", "available", "Available ", " Available"],
)
def test_every_noncanonical_status_variant_is_rejected(
    tmp_path: Path,
    invalid_status: object,
) -> None:
    source = create_synthetic_source(
        tmp_path / "invalid-status.sqlite",
        [("Green flag", "Quentin", "2026-01-01", invalid_status)],
    )
    report = tmp_path / "invalid-status.json"

    assert (
        importer.main(inspect_arguments(source, report))
        == importer.ExitCode.COMMAND_OR_VALIDATION_ERROR
    )
    categories = {
        error["category"]
        for error in json.loads(report.read_text(encoding="utf-8"))["source"][
            "validation_errors"
        ]
    }
    expected = (
        "null_status"
        if invalid_status is None
        else "blank_status"
        if not str(invalid_status).strip()
        else "unknown_or_noncanonical_status"
    )
    assert expected in categories


@pytest.mark.parametrize(
    "create_sql",
    [
        "CREATE TABLE availability (group_name TEXT, user_name TEXT, date TEXT, PRIMARY KEY (group_name, user_name, date))",
        "CREATE TABLE availability (group_name TEXT, user_name TEXT, date TEXT, status TEXT, extra TEXT, PRIMARY KEY (group_name, user_name, date))",
        "CREATE TABLE availability (group_name TEXT, user_name TEXT, date TEXT, status TEXT, PRIMARY KEY (user_name, group_name, date))",
        "CREATE TABLE availability (group_name INTEGER, user_name TEXT, date TEXT, status TEXT, PRIMARY KEY (group_name, user_name, date))",
    ],
)
def test_malformed_source_schema_is_reported_without_repair(
    tmp_path: Path,
    create_sql: str,
) -> None:
    source = create_synthetic_source(
        tmp_path / "malformed-schema.sqlite",
        create_sql=create_sql,
    )
    report = tmp_path / "malformed-schema.json"
    before = file_evidence(source)

    assert (
        importer.main(inspect_arguments(source, report))
        == importer.ExitCode.COMMAND_OR_VALIDATION_ERROR
    )
    assert file_evidence(source) == before
    assert json.loads(report.read_text(encoding="utf-8"))["source"]["schema_errors"]


def test_missing_table_is_fatal(tmp_path: Path) -> None:
    source = create_missing_table_source(tmp_path / "missing-table.sqlite")
    report = tmp_path / "missing-table.json"

    assert (
        importer.main(inspect_arguments(source, report))
        == importer.ExitCode.COMMAND_OR_VALIDATION_ERROR
    )
    assert json.loads(report.read_text(encoding="utf-8"))["source"][
        "schema_errors"
    ] == [{"category": "missing_table", "table": "availability"}]


def test_physical_duplicates_in_malformed_source_are_detected(tmp_path: Path) -> None:
    source = create_synthetic_source(
        tmp_path / "duplicates.sqlite",
        [
            ("Green flag", "Quentin", "2026-01-01", "Available"),
            ("Green flag", "Quentin", "2026-01-01", "Available"),
        ],
        create_sql="CREATE TABLE availability (group_name TEXT, user_name TEXT, date TEXT, status TEXT)",
    )
    inspection = importer.inspect_source(source)

    assert inspection["statistics"]["duplicate_physical_key_count"] == 1
    assert len(inspection["duplicate_physical_keys"]) == 1
    assert {error["category"] for error in inspection["validation_errors"]} >= {
        "duplicate_physical_keys"
    }


@pytest.mark.parametrize(
    "raw_json",
    [
        "not-json",
        '{"version":2,"groups":{}}',
        '{"version":1,"groups":{"Green flag":"Quentin","Green flag":"Arnaud","1D6":"Gaelle","Underdark":"Dembe"}}',
        '{"version":1,"groups":{"Green flag":"Quentin","1D6":"Gaelle"}}',
        '{"version":1,"groups":{"Green flag":"Quentin","1D6":"Gaelle","Underdark":"Dembe","Extra":"Quentin"}}',
        '{"version":1,"groups":{"Green flag":"Rico","1D6":"Gaelle","Underdark":"Dembe"}}',
        '{"version":1,"groups":{"Green flag":"","1D6":"Gaelle","Underdark":"Dembe"}}',
        '{"version":1,"groups":{"Green flag":1,"1D6":"Gaelle","Underdark":"Dembe"}}',
    ],
)
def test_owner_map_rejects_malformed_or_unapproved_assignments(
    tmp_path: Path,
    raw_json: str,
) -> None:
    owner_path = tmp_path / "owners.json"
    owner_path.write_text(raw_json, encoding="utf-8")
    with pytest.raises(importer.ImporterError):
        importer._load_owner_map(owner_path)


def test_one_explicit_user_may_own_multiple_groups(tmp_path: Path) -> None:
    owner_path = write_owner_map(
        tmp_path / "owners.json",
        {
            "Green flag": "Dembe",
            "1D6": "Dembe",
            "Underdark": "Dembe",
        },
    )
    assert set(importer._load_owner_map(owner_path)["groups"].values()) == {"Dembe"}


def test_source_backup_and_output_aliases_are_rejected(tmp_path: Path) -> None:
    source = create_synthetic_source(tmp_path / "alias.sqlite")
    with pytest.raises(importer.ImporterError, match="different"):
        importer._prepare_source_inputs(source, source, "0" * 64)

    before = file_evidence(source)
    assert (
        importer.main(inspect_arguments(source, source))
        == importer.ExitCode.COMMAND_OR_VALIDATION_ERROR
    )
    assert file_evidence(source) == before


def test_source_change_during_inspection_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_synthetic_source(tmp_path / "changing.sqlite", CANONICAL_ROWS)

    def change_source(path: Path) -> None:
        with path.open("ab") as output:
            output.write(b"changed-after-read")

    monkeypatch.setattr(importer, "_after_source_connection_closed", change_source)
    report = tmp_path / "changing-report.json"
    assert (
        importer.main(inspect_arguments(source, report))
        == importer.ExitCode.COMMAND_OR_VALIDATION_ERROR
    )
    assert not report.exists()


def test_frozen_backup_is_read_only_and_records_before_and_after_evidence(
    tmp_path: Path,
) -> None:
    source = create_synthetic_source(tmp_path / "source.sqlite", CANONICAL_ROWS)
    backup = copy_synthetic_source(source, tmp_path / "backup.sqlite")
    before = file_evidence(backup)

    evidence = importer._inspect_frozen_backup(backup, before[3])

    assert file_evidence(backup) == before
    assert evidence["metadata_before"] == evidence["metadata_after"]
    assert evidence["unchanged"] is True
    assert evidence["schema_fingerprint_sha256"]
    assert not list(tmp_path.glob("*-journal"))
    assert not list(tmp_path.glob("*-wal"))
    assert not list(tmp_path.glob("*-shm"))


def test_planned_checksums_cover_empty_group_months_and_admin_range(
    tmp_path: Path,
) -> None:
    source = create_synthetic_source(tmp_path / "source.sqlite", CANONICAL_ROWS)
    backup = copy_synthetic_source(source, tmp_path / "backup.sqlite")
    owner_map = importer._load_owner_map(write_owner_map(tmp_path / "owners.json"))
    inspection, backup_evidence = importer._validate_source_and_backup(
        source,
        backup,
        file_evidence(source)[3],
    )
    destination = importer.Destination(
        "IMPORT_DESTINATION_URL",
        "postgresql+psycopg://synthetic:password@127.0.0.1/synthetic",
    )
    mapping, plan = importer._build_expected_artifacts(
        inspection,
        owner_map,
        importer._utc_now(),
        destination,
        "0001_phase_1_domain_schema",
        backup_evidence,
    )

    importer._verify_plan_internal_consistency(plan)
    importer._verify_approved_contract(
        inspection=inspection,
        owner_map=owner_map,
        mapping=mapping,
        plan=plan,
    )
    group_month = plan["checksums"]["per_group_month_projection"]
    assert set(group_month) == set(EXPECTED_GROUPS)
    assert all(
        set(months) == {"2026-01", "2026-02", "2026-03"}
        for months in group_month.values()
    )
    assert group_month["1D6"]["2026-01"]["count"] == 0
    assert plan["checksums"]["admin_range_projection"] == {
        "minimum_date": "2026-01-01",
        "maximum_date": "2026-03-03",
        "count": len(plan["compatibility_projections"]),
        "sha256": plan["checksums"]["aggregate_projection_sha256"],
    }


def test_approved_identity_decisions_are_independently_revalidated(
    tmp_path: Path,
) -> None:
    source = create_synthetic_source(tmp_path / "source.sqlite", CANONICAL_ROWS)
    backup = copy_synthetic_source(source, tmp_path / "backup.sqlite")
    owner_map = importer._load_owner_map(write_owner_map(tmp_path / "owners.json"))
    inspection, backup_evidence = importer._validate_source_and_backup(
        source,
        backup,
        file_evidence(source)[3],
    )
    destination = importer.Destination(
        "IMPORT_DESTINATION_URL",
        "postgresql+psycopg://synthetic:password@127.0.0.1/synthetic",
    )
    mapping, plan = importer._build_expected_artifacts(
        inspection,
        owner_map,
        importer._utc_now(),
        destination,
        "0001_phase_1_domain_schema",
        backup_evidence,
    )
    tampered_mapping = json.loads(json.dumps(mapping))
    tampered_mapping["users"][0]["uuid"] = str(uuid.UUID(int=1))

    with pytest.raises(importer.ImporterError, match="user decisions"):
        importer._verify_approved_contract(
            inspection=inspection,
            owner_map=owner_map,
            mapping=tampered_mapping,
            plan=plan,
        )


def test_no_default_source_or_database_path_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synthetic_default = create_synthetic_source(tmp_path / "not-selected.sqlite")
    before = file_evidence(synthetic_default)
    monkeypatch.setenv("DATABASE_PATH", str(synthetic_default))

    assert (
        importer.main(["inspect", "--report-output", str(tmp_path / "report.json")])
        == importer.ExitCode.COMMAND_OR_VALIDATION_ERROR
    )
    assert file_evidence(synthetic_default) == before


def test_output_is_never_overwritten_and_success_is_restrictive(
    tmp_path: Path,
) -> None:
    source = create_synthetic_source(tmp_path / "source.sqlite")
    existing = tmp_path / "existing.json"
    existing.write_text("keep-me", encoding="utf-8")
    assert (
        importer.main(inspect_arguments(source, existing))
        == importer.ExitCode.COMMAND_OR_VALIDATION_ERROR
    )
    assert existing.read_text(encoding="utf-8") == "keep-me"

    report = tmp_path / "new-report.json"
    assert importer.main(inspect_arguments(source, report)) == importer.ExitCode.SUCCESS
    if os.name != "nt":
        assert stat.S_IMODE(report.stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.tmp"))


def test_public_cli_exit_codes_and_options_are_stable(tmp_path: Path) -> None:
    assert importer.main([]) == importer.ExitCode.COMMAND_OR_VALIDATION_ERROR
    parser_help = importer.build_parser().format_help()
    assert "inspect" in parser_help
    assert "plan" in parser_help
    assert "apply" in parser_help
    assert "verify" in parser_help
    assert "--destination-url" not in parser_help

    source = create_synthetic_source(tmp_path / "source.sqlite")
    report = tmp_path / "report.json"
    assert importer.main(inspect_arguments(source, report)) == importer.ExitCode.SUCCESS


def test_destination_password_is_redacted_from_public_cli_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = create_synthetic_source(tmp_path / "source.sqlite", CANONICAL_ROWS)
    backup = copy_synthetic_source(source, tmp_path / "backup.sqlite")
    owner_map = write_owner_map(tmp_path / "owners.json")
    expected = file_evidence(source)[3]
    encoded_password = "p%40ss%3Awo%2Frd%3F%23%5B%5D"
    decoded_password = "p@ss:wo/rd?#[]"
    monkeypatch.setenv(
        "IMPORT_DESTINATION_URL",
        f"postgresql+psycopg://user:{encoded_password}@127.0.0.1:1/synthetic",
    )

    assert (
        importer.main(plan_arguments(source, backup, owner_map, tmp_path, expected))
        == importer.ExitCode.COMMAND_OR_VALIDATION_ERROR
    )
    captured = capsys.readouterr()
    combined = f"{captured.out}\n{captured.err}"
    assert encoded_password not in combined
    assert decoded_password not in combined
    for artifact in tmp_path.glob("*.json"):
        assert encoded_password not in artifact.read_text(encoding="utf-8")
        assert decoded_password not in artifact.read_text(encoding="utf-8")
