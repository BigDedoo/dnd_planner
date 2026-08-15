"""Deterministic, fail-closed Phase 1B legacy data importer.

The public CLI has no database or path defaults.  SQLite sources are opened
read-only, PostgreSQL must already be at the Phase 1A Alembic head, and only
the ``apply`` subcommand can write domain rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import IntEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn
from urllib.parse import quote

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection, Engine

from backend.db import (
    create_database_runtime,
    redact_database_url,
    validate_database_url,
)
from backend.legacy_contract import (
    DOMAIN_TO_LEGACY_STATUS,
    GROUPS,
    LEGACY_CONTRACT_VERSION,
    LEGACY_IMPORT_NAMESPACE,
    LEGACY_TO_DOMAIN_STATUS,
    LEGACY_USERS,
    STATUS_MAP_VERSION,
    assert_no_nfc_collisions,
    canonical_legacy_identity,
    deterministic_legacy_uuid,
)
from backend.models import Availability, Group, GroupMembership, User

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BUILD_COMMIT_PATH = REPOSITORY_ROOT / ".dnd-planner-build-commit"
TOOL_VERSION = "1.0"
ARTIFACT_SCHEMA_VERSION = 1
OWNER_MAP_VERSION = 1
NORMALIZATION_POLICY_VERSION = 1
MAX_MISMATCH_EXAMPLES = 10
DOMAIN_TABLE_NAMES = ("users", "groups", "group_memberships", "availability")
EXPECTED_SOURCE_COLUMNS = ("group_name", "user_name", "date", "status")
EXPECTED_SOURCE_PRIMARY_KEY = ("group_name", "user_name", "date")
DESTINATION_ENV_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
SHA256_PATTERN = re.compile(r"[a-f0-9]{64}\Z")
GIT_COMMIT_PATTERN = re.compile(r"[a-f0-9]{40}\Z")
IMPORT_ADVISORY_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"dnd-planner-phase-1b-legacy-importer").digest()[:8],
    byteorder="big",
    signed=True,
)


class ExitCode(IntEnum):
    SUCCESS = 0
    COMMAND_OR_VALIDATION_ERROR = 2
    SOURCE_DATA_CONFLICT = 3
    UNSAFE_DESTINATION = 4
    DATABASE_WRITE_FAILURE = 5
    VERIFICATION_FAILURE = 6


class ImporterError(Exception):
    exit_code = ExitCode.COMMAND_OR_VALIDATION_ERROR


class SourceConflictError(ImporterError):
    exit_code = ExitCode.SOURCE_DATA_CONFLICT


class UnsafeDestinationError(ImporterError):
    exit_code = ExitCode.UNSAFE_DESTINATION


class DatabaseWriteError(ImporterError):
    exit_code = ExitCode.DATABASE_WRITE_FAILURE


class VerificationError(ImporterError):
    exit_code = ExitCode.VERIFICATION_FAILURE


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ImporterError(f"Invalid command: {message}")


class Destination:
    """Keep the usable URL private while exposing only a redacted form."""

    __slots__ = ("environment_name", "raw_url", "safe_url")

    def __init__(self, environment_name: str, raw_url: str) -> None:
        parsed = validate_database_url(raw_url)
        self.environment_name = environment_name
        self.raw_url = parsed.render_as_string(hide_password=False)
        self.safe_url = redact_database_url(parsed)

    def __repr__(self) -> str:
        return (
            f"Destination(environment={self.environment_name!r}, url={self.safe_url!r})"
        )


@dataclass(frozen=True)
class LegacyNormalizationPolicy:
    """One validated, immutable legacy-to-canonical migration policy."""

    version: int
    ignored_groups: tuple[str, ...]
    group_aliases: Mapping[str, str]
    user_aliases: Mapping[str, str]
    prefer_canonical_on_conflict: bool
    file_sha256: str
    canonical_sha256: str

    def canonical_document(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "ignored_groups": list(self.ignored_groups),
            "group_aliases": dict(self.group_aliases),
            "user_aliases": dict(self.user_aliases),
            "prefer_canonical_on_conflict": self.prefer_canonical_on_conflict,
        }

    def artifact_evidence(self) -> dict[str, Any]:
        return {
            **self.canonical_document(),
            "file_sha256": self.file_sha256,
            "canonical_sha256": self.canonical_sha256,
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_datetime(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ImporterError("Artifact contains an invalid UTC timestamp")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError:
        raise ImporterError("Artifact contains an invalid UTC timestamp") from None
    if parsed.tzinfo is None:
        raise ImporterError("Artifact contains a timezone-naive timestamp")
    return parsed.astimezone(timezone.utc)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _json_file_bytes(value: object) -> bytes:
    return _canonical_json_bytes(value) + b"\n"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical_json_bytes(value))


def _rows_checksum(rows: Iterable[Mapping[str, object]]) -> str:
    serialized = b"\n".join(_canonical_json_bytes(row) for row in rows)
    return _sha256_bytes(serialized)


def _finalize_artifact(document: dict[str, Any]) -> dict[str, Any]:
    finalized = dict(document)
    finalized["content_sha256"] = _sha256_json(document)
    return finalized


def _verify_finalized_artifact(
    document: object,
    *,
    expected_type: str,
) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ImporterError(f"{expected_type} artifact must contain a JSON object")
    if document.get("artifact_type") != expected_type:
        raise ImporterError(f"Expected a {expected_type} artifact")
    checksum = document.get("content_sha256")
    unsigned = {
        key: value for key, value in document.items() if key != "content_sha256"
    }
    if not isinstance(checksum, str) or checksum != _sha256_json(unsigned):
        raise ImporterError(f"{expected_type} artifact checksum is invalid")
    return document


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_metadata(path: Path) -> dict[str, Any]:
    file_stat = path.stat()
    return {
        "path": str(path),
        "size": file_stat.st_size,
        "mtime_ns": file_stat.st_mtime_ns,
        "sha256": _sha256_file(path),
        "write_bits_present": bool(
            file_stat.st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        ),
    }


def _resolve_input_file(raw_path: str | Path, label: str) -> Path:
    if not str(raw_path).strip():
        raise ImporterError(f"{label} path must be explicit and nonblank")
    try:
        path = Path(raw_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        raise ImporterError(f"{label} must name an existing regular file") from None
    try:
        mode = path.stat().st_mode
    except OSError:
        raise ImporterError(f"{label} must be readable") from None
    if not stat.S_ISREG(mode):
        raise ImporterError(f"{label} must name a regular file")
    return path


def _paths_alias(first: Path, second: Path) -> bool:
    if first == second:
        return True
    try:
        return os.path.samefile(first, second)
    except (FileNotFoundError, OSError):
        return False


def _validate_distinct_inputs(source: Path, backup: Path | None) -> None:
    if backup is not None and _paths_alias(source, backup):
        raise ImporterError("Source and backup must be different regular files")


def _preflight_output_paths(
    outputs: Sequence[Path],
    *,
    inputs: Sequence[Path],
) -> tuple[Path, ...]:
    resolved_outputs: list[Path] = []
    for raw_output in outputs:
        if not str(raw_output).strip():
            raise ImporterError("Every output path must be explicit and nonblank")
        output = raw_output.expanduser().resolve(strict=False)
        if not output.parent.is_dir():
            raise ImporterError("Every output parent directory must already exist")
        if any(_paths_alias(output, input_path) for input_path in inputs):
            raise ImporterError("An output path aliases a selected input file")
        if output.exists() or output.is_symlink():
            raise ImporterError(f"Refusing to overwrite output artifact: {output.name}")
        if output in resolved_outputs:
            raise ImporterError("Output artifact paths must be distinct")
        descriptor: int | None = None
        probe_path: Path | None = None
        try:
            descriptor, probe_name = tempfile.mkstemp(
                prefix=f".{output.name}.",
                suffix=".preflight",
                dir=output.parent,
            )
            probe_path = Path(probe_name)
            os.chmod(probe_path, 0o600)
            os.close(descriptor)
            descriptor = None
            probe_path.unlink()
        except OSError as exc:
            raise ImporterError(
                f"Output directory is not writable ({type(exc).__name__})"
            ) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if probe_path is not None:
                try:
                    probe_path.unlink()
                except FileNotFoundError:
                    pass
        resolved_outputs.append(output)
    return tuple(resolved_outputs)


def _atomic_write_json(path: Path, document: object) -> None:
    """Publish canonical JSON atomically without overwriting an existing file."""
    payload = _json_file_bytes(document)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    published = False
    try:
        os.chmod(temporary_path, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary_path, path)
            published = True
        except FileExistsError:
            raise ImporterError(f"Refusing to overwrite output artifact: {path.name}")
        except OSError as exc:
            if path.exists():
                raise ImporterError(
                    f"Refusing to overwrite output artifact: {path.name}"
                ) from None
            if os.name == "nt":
                try:
                    os.rename(temporary_path, path)
                    published = True
                except OSError:
                    pass
            if not published:
                raise ImporterError(
                    f"Could not publish output artifact: {path.name} "
                    f"({type(exc).__name__}); restrictive temporary evidence retained "
                    f"at {temporary_path}"
                ) from None
        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_descriptor = None
        if directory_descriptor is not None:
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    finally:
        if published:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ImporterError(f"JSON artifact contains duplicate key: {key}")
        result[key] = value
    return result


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        raw_bytes = path.read_bytes()
        loaded = json.loads(raw_bytes.decode("utf-8"), object_pairs_hook=_unique_object)
    except ImporterError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ImporterError(f"{label} must contain valid UTF-8 JSON") from None
    if not isinstance(loaded, dict):
        raise ImporterError(f"{label} must contain a JSON object")
    return loaded, _sha256_bytes(raw_bytes)


def _git_evidence() -> dict[str, Any]:
    def run(*arguments: str) -> str:
        try:
            result = subprocess.run(
                ["git", *arguments],
                cwd=REPOSITORY_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return "unavailable"
        return result.stdout.strip() if result.returncode == 0 else "unavailable"

    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain")
    if commit == "unavailable":
        try:
            built_commit = BUILD_COMMIT_PATH.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            built_commit = ""
        if GIT_COMMIT_PATTERN.fullmatch(built_commit):
            commit = built_commit
            status = ""
    return {"commit": commit, "working_tree_dirty": bool(status)}


def _report_header(artifact_type: str, started_at: datetime) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "git": _git_evidence(),
        "started_at": _format_datetime(started_at),
    }


def _finish_report(report: dict[str, Any], outcome: str) -> dict[str, Any]:
    finished = dict(report)
    finished["finished_at"] = _format_datetime(_utc_now())
    finished["transaction_outcome"] = outcome
    return _finalize_artifact(finished)


def _after_source_connection_closed(path: Path) -> None:
    """Test seam used to prove source-change detection."""
    del path


def _source_uri(path: Path) -> str:
    encoded = quote(str(path), safe="/:" if os.name == "nt" else "/")
    return f"file:{encoded}?mode=ro&immutable=1"


def _schema_inventory(connection: sqlite3.Connection) -> dict[str, Any]:
    table_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("availability",),
    ).fetchone()
    if table_row is None:
        return {
            "table_present": False,
            "create_sql": None,
            "columns": [],
            "indexes": [],
        }

    columns = [
        {
            "position": row[0],
            "name": row[1],
            "declared_type": row[2],
            "not_null": bool(row[3]),
            "default": row[4],
            "primary_key_position": row[5],
        }
        for row in connection.execute('PRAGMA table_info("availability")')
    ]
    indexes: list[dict[str, Any]] = []
    for row in connection.execute('PRAGMA index_list("availability")'):
        index_name = row[1]
        index_sql_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            (index_name,),
        ).fetchone()
        indexes.append(
            {
                "name": index_name,
                "unique": bool(row[2]),
                "origin": row[3],
                "partial": bool(row[4]),
                "columns": [
                    info[2]
                    for info in connection.execute(
                        f'PRAGMA index_info("{index_name.replace(chr(34), chr(34) * 2)}")'
                    )
                ],
                "sql": index_sql_row[0] if index_sql_row else None,
            }
        )
    indexes.sort(key=lambda index: str(index["name"]))
    return {
        "table_present": True,
        "create_sql": table_row[0],
        "columns": columns,
        "indexes": indexes,
    }


def _schema_errors(schema: Mapping[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not schema["table_present"]:
        return [{"category": "missing_table", "table": "availability"}]
    columns = schema["columns"]
    names = tuple(column["name"] for column in columns)
    if names != EXPECTED_SOURCE_COLUMNS:
        errors.append(
            {
                "category": "column_layout_mismatch",
                "expected": list(EXPECTED_SOURCE_COLUMNS),
                "actual": list(names),
            }
        )
    incompatible_types = [
        column["name"]
        for column in columns
        if str(column["declared_type"]).strip().upper() != "TEXT"
    ]
    if incompatible_types:
        errors.append(
            {
                "category": "incompatible_column_type",
                "columns": incompatible_types,
            }
        )
    primary_key = tuple(
        column["name"]
        for column in sorted(
            columns,
            key=lambda column: int(column["primary_key_position"] or 999),
        )
        if column["primary_key_position"]
    )
    if primary_key != EXPECTED_SOURCE_PRIMARY_KEY:
        errors.append(
            {
                "category": "primary_key_mismatch",
                "expected": list(EXPECTED_SOURCE_PRIMARY_KEY),
                "actual": list(primary_key),
            }
        )
    return errors


def _display_value(value: object) -> str:
    return "<null>" if value is None else str(value)


def _sorted_counter(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _validate_source_rows_without_policy(
    rows: list[tuple[Any, Any, Any, Any]],
) -> dict[str, Any]:
    validation_errors: list[dict[str, Any]] = []
    physical_coordinates: defaultdict[tuple[Any, Any, Any], list[int]] = defaultdict(
        list
    )
    logical_rows: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    valid_facts: list[dict[str, str]] = []
    known_users = set(LEGACY_USERS)

    group_counts: Counter[str] = Counter()
    user_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    month_counts: Counter[str] = Counter()
    discovered_groups: set[str] = set()
    discovered_users: set[str] = set()
    discovered_dates: set[str] = set()
    discovered_statuses: set[str] = set()

    for ordinal, (group_name, user_name, raw_day, raw_status) in enumerate(rows, 1):
        physical_coordinates[(group_name, user_name, raw_day)].append(ordinal)
        group_label = _display_value(group_name)
        user_label = _display_value(user_name)
        date_label = _display_value(raw_day)
        status_label = _display_value(raw_status)
        group_counts[group_label] += 1
        user_counts[user_label] += 1
        status_counts[status_label] += 1
        discovered_groups.add(group_label)
        discovered_users.add(user_label)
        discovered_dates.add(date_label)
        discovered_statuses.add(status_label)

        row_errors: list[str] = []
        if group_name is None:
            row_errors.append("null_group_name")
        elif not isinstance(group_name, str) or not group_name.strip():
            row_errors.append("blank_group_name")
        elif group_name not in GROUPS:
            row_errors.append("unknown_or_noncanonical_group")

        if user_name is None:
            row_errors.append("null_user_name")
        elif not isinstance(user_name, str) or not user_name.strip():
            row_errors.append("blank_user_name")
        elif user_name not in known_users:
            row_errors.append("unknown_or_noncanonical_user")
        elif isinstance(group_name, str) and group_name in GROUPS:
            if user_name not in GROUPS[group_name]:
                row_errors.append("user_not_in_group")

        parsed_day: date | None = None
        if raw_day is None:
            row_errors.append("null_date")
        elif not isinstance(raw_day, str):
            row_errors.append("malformed_date")
        else:
            try:
                parsed_day = date.fromisoformat(raw_day)
            except ValueError:
                row_errors.append("malformed_date")
            else:
                if parsed_day.isoformat() != raw_day:
                    row_errors.append("noncanonical_date")
                else:
                    month_counts[raw_day[:7]] += 1

        if raw_status is None:
            row_errors.append("null_status")
        elif not isinstance(raw_status, str) or not raw_status.strip():
            row_errors.append("blank_status")
        elif raw_status not in LEGACY_TO_DOMAIN_STATUS:
            row_errors.append("unknown_or_noncanonical_status")

        for category in row_errors:
            validation_errors.append(
                {
                    "category": category,
                    "source_ordinal": ordinal,
                    "coordinate": {
                        "group_name": group_name,
                        "user_name": user_name,
                        "date": raw_day,
                        "status": raw_status,
                    },
                }
            )

        if not row_errors:
            assert isinstance(group_name, str)
            assert isinstance(user_name, str)
            assert isinstance(raw_day, str)
            assert isinstance(raw_status, str)
            assert parsed_day is not None
            logical_rows[(user_name, raw_day)].append(
                {
                    "source_ordinal": ordinal,
                    "group_name": group_name,
                    "user_name": user_name,
                    "date": raw_day,
                    "status": raw_status,
                }
            )

    duplicate_physical_keys = [
        {
            "coordinate": {
                "group_name": key[0],
                "user_name": key[1],
                "date": key[2],
            },
            "source_ordinals": ordinals,
        }
        for key, ordinals in physical_coordinates.items()
        if len(ordinals) > 1
    ]
    if duplicate_physical_keys:
        validation_errors.append(
            {
                "category": "duplicate_physical_keys",
                "count": len(duplicate_physical_keys),
            }
        )

    repeated_identical: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for (user_name, raw_day), source_rows in sorted(logical_rows.items()):
        statuses = sorted({row["status"] for row in source_rows})
        if len(statuses) > 1:
            conflicts.append(
                {
                    "user_name": user_name,
                    "date": raw_day,
                    "statuses": statuses,
                    "source_rows": source_rows,
                }
            )
            continue
        if len(source_rows) > 1:
            repeated_identical.append(
                {
                    "user_name": user_name,
                    "date": raw_day,
                    "status": statuses[0],
                    "count": len(source_rows),
                    "source_rows": source_rows,
                }
            )
        valid_facts.append(
            {
                "user_name": user_name,
                "day": raw_day,
                "legacy_status": statuses[0],
                "status": LEGACY_TO_DOMAIN_STATUS[statuses[0]],
            }
        )

    valid_facts.sort(key=lambda fact: (fact["user_name"], fact["day"]))
    valid_dates = [fact["day"] for fact in valid_facts]
    statistics = {
        "raw_row_count": len(rows),
        "distinct_physical_key_count": len(physical_coordinates),
        "distinct_logical_user_day_count": len(logical_rows),
        "distinct_groups": sorted(discovered_groups),
        "distinct_users": sorted(discovered_users),
        "distinct_dates": sorted(discovered_dates),
        "distinct_statuses": sorted(discovered_statuses),
        "minimum_date": min(valid_dates) if valid_dates else None,
        "maximum_date": max(valid_dates) if valid_dates else None,
        "counts_by_status": _sorted_counter(status_counts),
        "counts_by_user": _sorted_counter(user_counts),
        "counts_by_group": _sorted_counter(group_counts),
        "counts_by_month": _sorted_counter(month_counts),
        "duplicate_physical_key_count": len(duplicate_physical_keys),
        "repeated_identical_logical_fact_count": len(repeated_identical),
        "conflicting_logical_fact_count": len(conflicts),
        "validation_error_count": len(validation_errors),
    }
    return {
        "statistics": statistics,
        "duplicate_physical_keys": duplicate_physical_keys,
        "repeated_identical_logical_facts": repeated_identical,
        "conflicting_logical_facts": conflicts,
        "validation_errors": validation_errors,
        "logical_facts": valid_facts,
    }


def _normalization_source_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_ordinal": row["source_ordinal"],
        "original_group": row["group_name"],
        "original_user": row["user_name"],
        "date": row["date"],
        "original_status": row["status"],
        "canonical_group": row.get("canonical_group_name"),
        "canonical_user": row.get("canonical_user_name"),
        "group_alias_applied": bool(row.get("group_alias_applied")),
        "user_alias_applied": bool(row.get("user_alias_applied")),
    }


def _normalization_resolution_event(
    *,
    user_name: str,
    raw_day: str,
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
    discarded: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    statuses_before = sorted({str(row["status"]) for row in before})
    statuses_after = sorted({str(row["status"]) for row in after})
    if len(statuses_before) <= 1 or statuses_before == statuses_after:
        return None
    return {
        "user_name": user_name,
        "date": raw_day,
        "statuses_before": statuses_before,
        "statuses_after": statuses_after,
        "preferred_source_rows": [_normalization_source_row(row) for row in after],
        "discarded_source_rows": [_normalization_source_row(row) for row in discarded],
    }


def _validate_source_rows_with_policy(
    rows: list[tuple[Any, Any, Any, Any]],
    policy: LegacyNormalizationPolicy,
) -> dict[str, Any]:
    validation_errors: list[dict[str, Any]] = []
    physical_coordinates: defaultdict[tuple[Any, Any, Any], list[int]] = defaultdict(
        list
    )
    logical_rows: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    raw_original_logical_keys: set[tuple[str, str]] = set()
    decisions: list[dict[str, Any]] = []
    decisions_by_ordinal: dict[int, dict[str, Any]] = {}

    group_counts: Counter[str] = Counter()
    user_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    month_counts: Counter[str] = Counter()
    ignored_group_counts: Counter[str] = Counter()
    discovered_groups: set[str] = set()
    discovered_users: set[str] = set()
    discovered_dates: set[str] = set()
    discovered_statuses: set[str] = set()
    canonical_groups: set[str] = set()
    canonical_users: set[str] = set()
    group_alias_row_count = 0
    user_alias_row_count = 0
    ignored_rows: list[dict[str, Any]] = []

    for ordinal, (group_name, user_name, raw_day, raw_status) in enumerate(rows, 1):
        physical_coordinates[(group_name, user_name, raw_day)].append(ordinal)
        group_label = _display_value(group_name)
        user_label = _display_value(user_name)
        date_label = _display_value(raw_day)
        status_label = _display_value(raw_status)
        group_counts[group_label] += 1
        user_counts[user_label] += 1
        status_counts[status_label] += 1
        discovered_groups.add(group_label)
        discovered_users.add(user_label)
        discovered_dates.add(date_label)
        discovered_statuses.add(status_label)

        row_errors: list[str] = []
        group_is_usable = isinstance(group_name, str) and bool(group_name.strip())
        user_is_usable = isinstance(user_name, str) and bool(user_name.strip())
        ignored = group_is_usable and group_name in policy.ignored_groups
        canonical_group: str | None = None
        canonical_user: str | None = None
        group_alias_applied = False
        user_alias_applied = False

        if group_name is None:
            row_errors.append("null_group_name")
        elif not group_is_usable:
            row_errors.append("blank_group_name")
        elif ignored:
            ignored_group_counts[group_name] += 1
        else:
            group_alias_applied = group_name in policy.group_aliases
            canonical_group = policy.group_aliases.get(group_name, group_name)
            if canonical_group not in GROUPS:
                row_errors.append("unknown_or_noncanonical_group")

        if user_name is None:
            row_errors.append("null_user_name")
        elif not user_is_usable:
            row_errors.append("blank_user_name")
        elif not ignored:
            user_alias_applied = user_name in policy.user_aliases
            canonical_user = policy.user_aliases.get(user_name, user_name)
            if canonical_user not in LEGACY_USERS:
                row_errors.append("unknown_or_noncanonical_user")
            elif (
                canonical_group in GROUPS
                and canonical_user not in GROUPS[canonical_group]
            ):
                row_errors.append("user_not_in_group")

        if not ignored and group_alias_applied:
            group_alias_row_count += 1
        if not ignored and user_alias_applied:
            user_alias_row_count += 1

        parsed_day: date | None = None
        if raw_day is None:
            row_errors.append("null_date")
        elif not isinstance(raw_day, str):
            row_errors.append("malformed_date")
        else:
            try:
                parsed_day = date.fromisoformat(raw_day)
            except ValueError:
                row_errors.append("malformed_date")
            else:
                if parsed_day.isoformat() != raw_day:
                    row_errors.append("noncanonical_date")
                else:
                    month_counts[raw_day[:7]] += 1

        if raw_status is None:
            row_errors.append("null_status")
        elif not isinstance(raw_status, str) or not raw_status.strip():
            row_errors.append("blank_status")
        elif raw_status not in LEGACY_TO_DOMAIN_STATUS:
            row_errors.append("unknown_or_noncanonical_status")

        decision = {
            "source_ordinal": ordinal,
            "original_group": group_name,
            "original_user": user_name,
            "date": raw_day,
            "original_status": raw_status,
            "canonical_group": canonical_group,
            "canonical_user": canonical_user,
            "group_alias_applied": group_alias_applied,
            "user_alias_applied": user_alias_applied,
            "disposition": (
                "invalid" if row_errors else "ignored_group" if ignored else "candidate"
            ),
        }
        decisions.append(decision)
        decisions_by_ordinal[ordinal] = decision

        for category in row_errors:
            validation_errors.append(
                {
                    "category": category,
                    "source_ordinal": ordinal,
                    "coordinate": {
                        "group_name": group_name,
                        "user_name": user_name,
                        "date": raw_day,
                        "status": raw_status,
                    },
                }
            )

        source_row = {
            "source_ordinal": ordinal,
            "group_name": group_name,
            "user_name": user_name,
            "date": raw_day,
            "status": raw_status,
            "canonical_group_name": canonical_group,
            "canonical_user_name": canonical_user,
            "group_alias_applied": group_alias_applied,
            "user_alias_applied": user_alias_applied,
        }
        if ignored:
            ignored_rows.append(_normalization_source_row(source_row))
        if row_errors or ignored:
            continue

        assert isinstance(group_name, str)
        assert isinstance(user_name, str)
        assert isinstance(raw_day, str)
        assert isinstance(raw_status, str)
        assert canonical_group is not None
        assert canonical_user is not None
        assert parsed_day is not None
        canonical_groups.add(canonical_group)
        canonical_users.add(canonical_user)
        raw_original_logical_keys.add((user_name, raw_day))
        logical_rows[(canonical_user, raw_day)].append(source_row)

    duplicate_physical_keys = [
        {
            "coordinate": {
                "group_name": key[0],
                "user_name": key[1],
                "date": key[2],
            },
            "source_ordinals": ordinals,
        }
        for key, ordinals in physical_coordinates.items()
        if len(ordinals) > 1
    ]
    if duplicate_physical_keys:
        validation_errors.append(
            {
                "category": "duplicate_physical_keys",
                "count": len(duplicate_physical_keys),
            }
        )

    raw_collisions: list[dict[str, Any]] = []
    user_resolutions: list[dict[str, Any]] = []
    group_resolutions: list[dict[str, Any]] = []
    repeated_identical: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    valid_facts: list[dict[str, str]] = []

    for (canonical_user, raw_day), source_rows in sorted(logical_rows.items()):
        raw_statuses = sorted({str(row["status"]) for row in source_rows})
        if len(raw_statuses) > 1:
            raw_collisions.append(
                {
                    "user_name": canonical_user,
                    "date": raw_day,
                    "statuses": raw_statuses,
                    "source_rows": [
                        _normalization_source_row(row) for row in source_rows
                    ],
                }
            )

        working = list(source_rows)
        if policy.prefer_canonical_on_conflict:
            canonical_user_rows = [
                row for row in working if row["user_name"] == canonical_user
            ]
            alias_user_rows = [
                row for row in working if row["user_name"] != canonical_user
            ]
            if canonical_user_rows and alias_user_rows:
                event = _normalization_resolution_event(
                    user_name=canonical_user,
                    raw_day=raw_day,
                    before=working,
                    after=canonical_user_rows,
                    discarded=alias_user_rows,
                )
                if event is not None:
                    user_resolutions.append(event)
                for row in alias_user_rows:
                    decisions_by_ordinal[row["source_ordinal"]]["disposition"] = (
                        "overridden_by_canonical_user"
                    )
                working = canonical_user_rows

            for canonical_group in sorted(
                {str(row["canonical_group_name"]) for row in working}
            ):
                same_group = [
                    row
                    for row in working
                    if row["canonical_group_name"] == canonical_group
                ]
                canonical_group_rows = [
                    row for row in same_group if row["group_name"] == canonical_group
                ]
                alias_group_rows = [
                    row for row in same_group if row["group_name"] != canonical_group
                ]
                if not canonical_group_rows or not alias_group_rows:
                    continue
                after = [row for row in working if row not in alias_group_rows]
                event = _normalization_resolution_event(
                    user_name=canonical_user,
                    raw_day=raw_day,
                    before=same_group,
                    after=canonical_group_rows,
                    discarded=alias_group_rows,
                )
                if event is not None:
                    event["canonical_group"] = canonical_group
                    group_resolutions.append(event)
                for row in alias_group_rows:
                    decisions_by_ordinal[row["source_ordinal"]]["disposition"] = (
                        "overridden_by_canonical_group"
                    )
                working = after

        statuses = sorted({str(row["status"]) for row in working})
        if len(statuses) > 1:
            for row in working:
                decisions_by_ordinal[row["source_ordinal"]]["disposition"] = (
                    "unresolved_conflict"
                )
            conflicts.append(
                {
                    "user_name": canonical_user,
                    "date": raw_day,
                    "statuses": statuses,
                    "source_rows": [_normalization_source_row(row) for row in working],
                }
            )
            continue

        for row in working:
            decisions_by_ordinal[row["source_ordinal"]]["disposition"] = (
                "contributes_to_logical_fact"
            )
        if len(working) > 1:
            repeated_identical.append(
                {
                    "user_name": canonical_user,
                    "date": raw_day,
                    "status": statuses[0],
                    "count": len(working),
                    "source_rows": [_normalization_source_row(row) for row in working],
                }
            )
        valid_facts.append(
            {
                "user_name": canonical_user,
                "day": raw_day,
                "legacy_status": statuses[0],
                "status": LEGACY_TO_DOMAIN_STATUS[statuses[0]],
            }
        )

    valid_facts.sort(key=lambda fact: (fact["user_name"], fact["day"]))
    valid_dates = [fact["day"] for fact in valid_facts]
    normalized_status_counts = Counter(fact["legacy_status"] for fact in valid_facts)
    statistics = {
        "raw_row_count": len(rows),
        "distinct_physical_key_count": len(physical_coordinates),
        "distinct_logical_user_day_count": len(logical_rows),
        "distinct_groups": sorted(discovered_groups),
        "distinct_users": sorted(discovered_users),
        "distinct_dates": sorted(discovered_dates),
        "distinct_statuses": sorted(discovered_statuses),
        "minimum_date": min(valid_dates) if valid_dates else None,
        "maximum_date": max(valid_dates) if valid_dates else None,
        "counts_by_status": _sorted_counter(status_counts),
        "counts_by_user": _sorted_counter(user_counts),
        "counts_by_group": _sorted_counter(group_counts),
        "counts_by_month": _sorted_counter(month_counts),
        "duplicate_physical_key_count": len(duplicate_physical_keys),
        "repeated_identical_logical_fact_count": len(repeated_identical),
        "conflicting_logical_fact_count": len(conflicts),
        "validation_error_count": len(validation_errors),
    }
    normalization = {
        "policy": policy.artifact_evidence(),
        "raw_physical_row_count": len(rows),
        "raw_distinct_user_day_count": len(raw_original_logical_keys),
        "ignored_row_count": sum(ignored_group_counts.values()),
        "ignored_rows_by_reason": {
            "explicit_policy_group": sum(ignored_group_counts.values())
        },
        "ignored_rows_by_group": _sorted_counter(ignored_group_counts),
        "group_alias_row_count": group_alias_row_count,
        "user_alias_row_count": user_alias_row_count,
        "raw_logical_collision_count": len(raw_collisions),
        "conflicts_resolved_by_canonical_user_precedence_count": len(user_resolutions),
        "conflicts_resolved_by_canonical_group_precedence_count": len(
            group_resolutions
        ),
        "remaining_unresolved_conflict_count": len(conflicts),
        "canonical_users": sorted(canonical_users),
        "canonical_groups": sorted(canonical_groups),
        "normalized_global_user_day_fact_count": len(valid_facts),
        "normalized_counts_by_status": _sorted_counter(normalized_status_counts),
        "ignored_rows": ignored_rows,
        "raw_logical_collisions": raw_collisions,
        "conflicts_resolved_by_canonical_user_precedence": user_resolutions,
        "conflicts_resolved_by_canonical_group_precedence": group_resolutions,
        "remaining_unresolved_conflicts": conflicts,
        "row_decisions": decisions,
    }
    return {
        "statistics": statistics,
        "duplicate_physical_keys": duplicate_physical_keys,
        "repeated_identical_logical_facts": repeated_identical,
        "conflicting_logical_facts": conflicts,
        "validation_errors": validation_errors,
        "logical_facts": valid_facts,
        "normalization": normalization,
    }


def _validate_source_rows(
    rows: list[tuple[Any, Any, Any, Any]],
    normalization_policy: LegacyNormalizationPolicy | None = None,
) -> dict[str, Any]:
    if normalization_policy is None:
        return _validate_source_rows_without_policy(rows)
    return _validate_source_rows_with_policy(rows, normalization_policy)


def inspect_source(
    source: Path,
    normalization_policy: LegacyNormalizationPolicy | None = None,
) -> dict[str, Any]:
    """Inspect one explicit SQLite file without permitting a write connection."""
    source = _resolve_input_file(source, "Source SQLite")
    before = _file_metadata(source)
    rows: list[tuple[Any, Any, Any, Any]] = []
    try:
        connection = sqlite3.connect(_source_uri(source), uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            schema = _schema_inventory(connection)
            schema_validation_errors = _schema_errors(schema)
            available_columns = tuple(
                column["name"] for column in schema.get("columns", [])
            )
            if available_columns == EXPECTED_SOURCE_COLUMNS:
                rows = connection.execute(
                    "SELECT group_name, user_name, date, status "
                    "FROM availability "
                    "ORDER BY group_name, user_name, date, status"
                ).fetchall()
            connection.rollback()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ImporterError(
            f"Could not inspect the selected SQLite source ({type(exc).__name__})"
        ) from None

    _after_source_connection_closed(source)
    after = _file_metadata(source)
    if any(before[key] != after[key] for key in ("size", "mtime_ns", "sha256")):
        raise ImporterError("SQLite source changed while it was being inspected")

    row_validation = _validate_source_rows(rows, normalization_policy)
    schema_fingerprint_input = {
        "create_sql": schema.get("create_sql"),
        "columns": schema.get("columns", []),
        "indexes": schema.get("indexes", []),
    }
    return {
        "metadata_before": before,
        "metadata_after": after,
        "unchanged": True,
        "schema": {
            **schema,
            "fingerprint_sha256": _sha256_json(schema_fingerprint_input),
        },
        "schema_errors": schema_validation_errors,
        **row_validation,
    }


def _raise_for_source_problems(inspection: Mapping[str, Any]) -> None:
    if inspection["conflicting_logical_facts"]:
        raise SourceConflictError(
            "Source contains conflicting logical availability facts"
        )
    if inspection["schema_errors"] or inspection["validation_errors"]:
        raise ImporterError("Source schema or data validation failed")


def _validate_expected_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if SHA256_PATTERN.fullmatch(normalized) is None:
        raise ImporterError(
            "Expected source SHA-256 must contain 64 hexadecimal digits"
        )
    return normalized


def _load_owner_map(path: Path) -> dict[str, Any]:
    owner_document, file_checksum = _load_json(path, "Owner map")
    if owner_document.get("version") != OWNER_MAP_VERSION:
        raise ImporterError("Owner map version must be 1")
    owners = owner_document.get("groups")
    if not isinstance(owners, dict):
        raise ImporterError("Owner map groups must be a JSON object")
    expected_groups = set(GROUPS)
    actual_groups = set(owners)
    if actual_groups != expected_groups:
        raise ImporterError("Owner map must contain exactly the legacy groups")
    validated: dict[str, str] = {}
    for group_name, members in GROUPS.items():
        owner = owners[group_name]
        if not isinstance(owner, str) or not owner.strip():
            raise ImporterError("Every owner must be an exact nonblank member name")
        if owner not in members:
            raise ImporterError("Every owner must be a member of the selected group")
        validated[group_name] = owner
    return {
        "version": OWNER_MAP_VERSION,
        "groups": validated,
        "file_sha256": file_checksum,
        "canonical_sha256": _sha256_json(
            {"version": OWNER_MAP_VERSION, "groups": validated}
        ),
    }


def _alias_cycle(mapping: Mapping[str, str]) -> tuple[str, ...] | None:
    """Return one deterministic alias cycle, including its repeated start."""
    for start in sorted(mapping):
        positions: dict[str, int] = {}
        path: list[str] = []
        current = start
        while current in mapping:
            if current in positions:
                cycle = path[positions[current] :] + [current]
                return tuple(cycle)
            positions[current] = len(path)
            path.append(current)
            current = mapping[current]
    return None


def _validate_alias_mapping(
    raw_mapping: object,
    *,
    label: str,
    kind: str,
    canonical_values: Sequence[str],
) -> dict[str, str]:
    if not isinstance(raw_mapping, dict):
        raise ImporterError(f"Normalization policy {label} must be a JSON object")

    validated: dict[str, str] = {}
    for source, target in raw_mapping.items():
        if (
            not isinstance(source, str)
            or not source.strip()
            or source != source.strip()
            or not isinstance(target, str)
            or not target.strip()
            or target != target.strip()
        ):
            raise ImporterError(
                f"Normalization policy {label} must use exact nonblank strings"
            )
        if source == target:
            raise ImporterError(f"Normalization policy {label} contains a self alias")
        validated[source] = target

    cycle = _alias_cycle(validated)
    if cycle is not None:
        raise ImporterError(f"Normalization policy {label} contains an alias cycle")

    canonical_set = set(canonical_values)
    if set(validated) & canonical_set:
        raise ImporterError(
            f"Normalization policy {label} may not remap a canonical identity"
        )
    invalid_targets = sorted(set(validated.values()) - canonical_set)
    if invalid_targets:
        raise ImporterError(
            f"Normalization policy {label} targets an unknown canonical identity"
        )
    try:
        assert_no_nfc_collisions(kind, (*canonical_values, *validated))
    except ValueError as exc:
        raise ImporterError(str(exc)) from None
    return {source: validated[source] for source in sorted(validated)}


def _load_normalization_policy(path: Path) -> LegacyNormalizationPolicy:
    policy_document, file_checksum = _load_json(path, "Normalization policy")
    expected_fields = {
        "version",
        "ignored_groups",
        "group_aliases",
        "user_aliases",
        "prefer_canonical_on_conflict",
    }
    if set(policy_document) != expected_fields:
        raise ImporterError(
            "Normalization policy must contain exactly the version 1 fields"
        )
    if (
        type(policy_document["version"]) is not int
        or policy_document["version"] != NORMALIZATION_POLICY_VERSION
    ):
        raise ImporterError("Normalization policy version must be 1")

    raw_ignored_groups = policy_document["ignored_groups"]
    if not isinstance(raw_ignored_groups, list):
        raise ImporterError("Normalization policy ignored_groups must be a JSON array")
    if any(
        not isinstance(group_name, str)
        or not group_name.strip()
        or group_name != group_name.strip()
        for group_name in raw_ignored_groups
    ):
        raise ImporterError(
            "Normalization policy ignored groups must be exact nonblank strings"
        )
    if len(set(raw_ignored_groups)) != len(raw_ignored_groups):
        raise ImporterError("Normalization policy ignored groups contain duplicates")
    if set(raw_ignored_groups) & set(GROUPS):
        raise ImporterError(
            "Normalization policy may not ignore a canonical production group"
        )
    try:
        assert_no_nfc_collisions("group", (*GROUPS, *raw_ignored_groups))
    except ValueError as exc:
        raise ImporterError(str(exc)) from None

    group_aliases = _validate_alias_mapping(
        policy_document["group_aliases"],
        label="group_aliases",
        kind="group",
        canonical_values=tuple(GROUPS),
    )
    user_aliases = _validate_alias_mapping(
        policy_document["user_aliases"],
        label="user_aliases",
        kind="user",
        canonical_values=LEGACY_USERS,
    )
    ignored_groups = tuple(sorted(raw_ignored_groups))
    if set(ignored_groups) & set(group_aliases):
        raise ImporterError(
            "Normalization policy group aliases and ignored groups are ambiguous"
        )
    try:
        assert_no_nfc_collisions("group", (*GROUPS, *ignored_groups, *group_aliases))
    except ValueError as exc:
        raise ImporterError(str(exc)) from None

    prefer_canonical = policy_document["prefer_canonical_on_conflict"]
    if type(prefer_canonical) is not bool:
        raise ImporterError(
            "Normalization policy prefer_canonical_on_conflict must be boolean"
        )

    canonical_document = {
        "version": NORMALIZATION_POLICY_VERSION,
        "ignored_groups": list(ignored_groups),
        "group_aliases": group_aliases,
        "user_aliases": user_aliases,
        "prefer_canonical_on_conflict": prefer_canonical,
    }
    return LegacyNormalizationPolicy(
        version=NORMALIZATION_POLICY_VERSION,
        ignored_groups=ignored_groups,
        group_aliases=MappingProxyType(group_aliases),
        user_aliases=MappingProxyType(user_aliases),
        prefer_canonical_on_conflict=prefer_canonical,
        file_sha256=file_checksum,
        canonical_sha256=_sha256_json(canonical_document),
    )


def _identity_records(kind: str, values: Sequence[str]) -> list[dict[str, str]]:
    typed_kind = "user" if kind == "user" else "group" if kind == "group" else None
    if typed_kind is None:
        raise ImporterError("Identity kind must be user or group")
    value_tuple = tuple(values)
    try:
        assert_no_nfc_collisions(typed_kind, value_tuple)
    except ValueError as exc:
        raise ImporterError(str(exc)) from None
    records = [
        {
            "source_value": value,
            "canonical_name": canonical_legacy_identity(typed_kind, value),
            "uuid": str(deterministic_legacy_uuid(typed_kind, value)),
        }
        for value in value_tuple
    ]
    records.sort(key=lambda record: record["source_value"])
    return records


def _sort_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: _canonical_json_bytes(row))


def _compatibility_projections(
    logical_facts: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    projections = [
        {
            "group_name": group_name,
            "user_name": fact["user_name"],
            "date": fact["day"],
            "status": fact["legacy_status"],
        }
        for fact in logical_facts
        for group_name, members in GROUPS.items()
        if fact["user_name"] in members
    ]
    return _sort_rows(projections)


def _checksum_bundle(
    rows: Mapping[str, Sequence[dict[str, Any]]],
    logical_facts: Sequence[dict[str, str]],
    projections: Sequence[dict[str, str]],
) -> dict[str, Any]:
    per_user: dict[str, Any] = {}
    for user_name in LEGACY_USERS:
        user_facts = [fact for fact in logical_facts if fact["user_name"] == user_name]
        days = [fact["day"] for fact in user_facts]
        per_user[user_name] = {
            "count": len(user_facts),
            "minimum_date": min(days) if days else None,
            "maximum_date": max(days) if days else None,
            "sha256": _rows_checksum(user_facts),
        }

    source_months = sorted({fact["day"][:7] for fact in logical_facts})
    projection_groups: defaultdict[tuple[str, str], list[dict[str, str]]] = defaultdict(
        list
    )
    for projection in projections:
        projection_groups[(projection["group_name"], projection["date"][:7])].append(
            projection
        )
    per_group_month = {
        group_name: {
            month: {
                "count": len(projection_groups[(group_name, month)]),
                "sha256": _rows_checksum(projection_groups[(group_name, month)]),
            }
            for month in source_months
        }
        for group_name in GROUPS
    }
    projection_days = [projection["date"] for projection in projections]
    return {
        "tables": {
            table_name: _rows_checksum(rows[table_name])
            for table_name in DOMAIN_TABLE_NAMES
        },
        "logical_user_day_status_sha256": _rows_checksum(logical_facts),
        "per_user": per_user,
        "per_group_month_projection": per_group_month,
        "admin_range_projection": {
            "minimum_date": min(projection_days) if projection_days else None,
            "maximum_date": max(projection_days) if projection_days else None,
            "count": len(projections),
            "sha256": _rows_checksum(projections),
        },
        "aggregate_projection_sha256": _rows_checksum(projections),
    }


def _expected_import_state(
    logical_facts: Sequence[dict[str, str]],
    owner_groups: Mapping[str, str],
    timestamp: str,
) -> dict[str, Any]:
    canonical_logical_facts = _sort_rows([dict(fact) for fact in logical_facts])
    user_identities = _identity_records("user", LEGACY_USERS)
    group_identities = _identity_records("group", tuple(GROUPS))
    user_ids = {record["source_value"]: record["uuid"] for record in user_identities}
    group_ids = {record["source_value"]: record["uuid"] for record in group_identities}
    rows = {
        "users": _sort_rows(
            [
                {
                    "id": user_ids[user_name],
                    "account_id": None,
                    "auth_provider": None,
                    "auth_subject": None,
                    "email": None,
                    "display_name": user_name,
                    "timezone": "UTC",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
                for user_name in LEGACY_USERS
            ]
        ),
        "groups": _sort_rows(
            [
                {
                    "id": group_ids[group_name],
                    "name": group_name,
                    "timezone": "UTC",
                    "description": None,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
                for group_name in GROUPS
            ]
        ),
        "group_memberships": _sort_rows(
            [
                {
                    "group_id": group_ids[group_name],
                    "user_id": user_ids[user_name],
                    "role": (
                        "owner" if owner_groups[group_name] == user_name else "member"
                    ),
                    "display_order": display_order,
                    "joined_at": timestamp,
                }
                for group_name, members in GROUPS.items()
                for display_order, user_name in enumerate(members)
            ]
        ),
        "availability": _sort_rows(
            [
                {
                    "user_id": user_ids[fact["user_name"]],
                    "day": fact["day"],
                    "status": fact["status"],
                    "updated_at": timestamp,
                }
                for fact in canonical_logical_facts
            ]
        ),
    }
    projections = _compatibility_projections(canonical_logical_facts)
    return {
        "user_identities": user_identities,
        "group_identities": group_identities,
        "rows": rows,
        "logical_facts": canonical_logical_facts,
        "projections": projections,
        "checksums": _checksum_bundle(rows, canonical_logical_facts, projections),
    }


def _build_expected_artifacts(
    inspection: Mapping[str, Any],
    owner_map: Mapping[str, Any],
    imported_at: datetime,
    destination: Destination,
    destination_revision: str,
    backup_metadata: Mapping[str, Any],
    normalization_policy: LegacyNormalizationPolicy | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    timestamp = _format_datetime(imported_at)
    state = _expected_import_state(
        list(inspection["logical_facts"]), owner_map["groups"], timestamp
    )
    logical_facts = state["logical_facts"]
    user_identities = state["user_identities"]
    group_identities = state["group_identities"]
    rows = state["rows"]
    memberships = rows["group_memberships"]
    projections = state["projections"]
    checksums = state["checksums"]
    status_contract = {
        "version": STATUS_MAP_VERSION,
        "legacy_to_domain": dict(LEGACY_TO_DOMAIN_STATUS),
        "domain_to_legacy": dict(DOMAIN_TO_LEGACY_STATUS),
    }

    mapping_document = {
        "artifact_type": "identity_mapping",
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "git": _git_evidence(),
        "legacy_contract_version": LEGACY_CONTRACT_VERSION,
        "namespace": str(LEGACY_IMPORT_NAMESPACE),
        "imported_at": timestamp,
        "source_sha256": inspection["metadata_after"]["sha256"],
        "destination": {
            "url": destination.safe_url,
            "alembic_revision": destination_revision,
        },
        "status_map": {
            **status_contract,
            "sha256": _sha256_json(status_contract),
        },
        "owner_map": {
            "version": owner_map["version"],
            "file_sha256": owner_map["file_sha256"],
            "canonical_sha256": owner_map["canonical_sha256"],
            "groups": dict(owner_map["groups"]),
        },
        "users": user_identities,
        "groups": group_identities,
        "memberships": memberships,
        "checksums": checksums,
    }
    if normalization_policy is not None:
        mapping_document["normalization_policy"] = (
            normalization_policy.artifact_evidence()
        )
    mapping = _finalize_artifact(mapping_document)
    mapping_file_sha256 = _sha256_bytes(_json_file_bytes(mapping))
    source_evidence = {
        "metadata": inspection["metadata_after"],
        "schema_fingerprint_sha256": inspection["schema"]["fingerprint_sha256"],
        "statistics": inspection["statistics"],
    }
    if normalization_policy is not None:
        source_evidence["normalization"] = inspection["normalization"]
    plan_document = {
        "artifact_type": "import_plan",
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "git": _git_evidence(),
        "legacy_contract_version": LEGACY_CONTRACT_VERSION,
        "namespace": str(LEGACY_IMPORT_NAMESPACE),
        "imported_at": timestamp,
        "source": source_evidence,
        "backup": dict(backup_metadata),
        "destination": {
            "url": destination.safe_url,
            "alembic_revision": destination_revision,
        },
        "status_map": {
            **status_contract,
            "sha256": _sha256_json(status_contract),
        },
        "owner_map": {
            "version": owner_map["version"],
            "file_sha256": owner_map["file_sha256"],
            "canonical_sha256": owner_map["canonical_sha256"],
            "groups": dict(owner_map["groups"]),
        },
        "identity_mapping_file_sha256": mapping_file_sha256,
        "rows": rows,
        "logical_facts": logical_facts,
        "compatibility_projections": projections,
        "checksums": checksums,
        "expected_counts": {
            table_name: len(rows[table_name]) for table_name in DOMAIN_TABLE_NAMES
        },
    }
    if normalization_policy is not None:
        plan_document["normalization_policy"] = normalization_policy.artifact_evidence()
    plan = _finalize_artifact(plan_document)
    return mapping, plan


def _resolve_destination(environment_name: str) -> Destination:
    if (
        not isinstance(environment_name, str)
        or DESTINATION_ENV_PATTERN.fullmatch(environment_name) is None
    ):
        raise ImporterError("Destination environment variable name is invalid")
    value = os.environ.get(environment_name)
    if value is None or not value.strip():
        raise ImporterError(
            f"Destination environment variable {environment_name} is missing or blank"
        )
    try:
        return Destination(environment_name, value)
    except Exception as exc:
        raise ImporterError(
            f"Destination environment variable is invalid ({type(exc).__name__})"
        ) from None


def _repository_head_revision() -> str:
    configuration = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    head = ScriptDirectory.from_config(configuration).get_current_head()
    if head is None:
        raise ImporterError("Repository has no Alembic head revision")
    return head


def _require_destination_revision(connection: Connection) -> str:
    expected = _repository_head_revision()
    try:
        actual = MigrationContext.configure(connection).get_current_revision()
    except Exception as exc:
        raise ImporterError(
            f"Could not read destination Alembic revision ({type(exc).__name__})"
        ) from None
    if actual != expected:
        raise ImporterError("Destination is not at the exact repository Alembic head")
    return actual


def _normalize_database_value(value: object) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return _format_datetime(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value
    return value


def _destination_snapshot(connection: Connection) -> dict[str, list[dict[str, Any]]]:
    table_objects = {
        "users": User.__table__,
        "groups": Group.__table__,
        "group_memberships": GroupMembership.__table__,
        "availability": Availability.__table__,
    }
    snapshot: dict[str, list[dict[str, Any]]] = {}
    try:
        for table_name, table in table_objects.items():
            rows = [
                {key: _normalize_database_value(value) for key, value in row.items()}
                for row in connection.execute(sa.select(table)).mappings()
            ]
            snapshot[table_name] = _sort_rows(rows)
    except Exception as exc:
        raise ImporterError(
            f"Could not read destination domain tables ({type(exc).__name__})"
        ) from None
    return snapshot


def _compare_rows(
    expected: Mapping[str, Sequence[dict[str, Any]]],
    actual: Mapping[str, Sequence[dict[str, Any]]],
) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    total = 0
    for table_name in DOMAIN_TABLE_NAMES:
        expected_serialized = Counter(
            _canonical_json_bytes(row).decode("utf-8") for row in expected[table_name]
        )
        actual_serialized = Counter(
            _canonical_json_bytes(row).decode("utf-8") for row in actual[table_name]
        )
        missing_values = list((expected_serialized - actual_serialized).elements())
        unexpected_values = list((actual_serialized - expected_serialized).elements())
        count = len(missing_values) + len(unexpected_values)
        total += count
        tables[table_name] = {
            "expected_count": len(expected[table_name]),
            "actual_count": len(actual[table_name]),
            "mismatch_count": count,
            "missing_count": len(missing_values),
            "unexpected_count": len(unexpected_values),
            "missing_examples": [
                json.loads(value) for value in missing_values[:MAX_MISMATCH_EXAMPLES]
            ],
            "unexpected_examples": [
                json.loads(value) for value in unexpected_values[:MAX_MISMATCH_EXAMPLES]
            ],
        }
    return {"total_mismatch_count": total, "tables": tables}


def _classify_destination(
    expected: Mapping[str, Sequence[dict[str, Any]]],
    actual: Mapping[str, Sequence[dict[str, Any]]],
) -> tuple[str, dict[str, Any]]:
    counts = {table: len(actual[table]) for table in DOMAIN_TABLE_NAMES}
    if all(count == 0 for count in counts.values()):
        return "empty", {"table_counts": counts, "total_mismatch_count": 0}
    comparison = _compare_rows(expected, actual)
    if comparison["total_mismatch_count"] == 0:
        return "exact_prior_import", {"table_counts": counts, **comparison}
    return "unsafe_nonempty", {"table_counts": counts, **comparison}


def _connect_engine(destination: Destination) -> tuple[Any, Engine]:
    runtime = create_database_runtime(destination.raw_url)
    return runtime, runtime.engine


def _load_artifact(path: Path, expected_type: str) -> tuple[dict[str, Any], str]:
    loaded, file_checksum = _load_json(path, expected_type)
    return _verify_finalized_artifact(
        loaded, expected_type=expected_type
    ), file_checksum


def _validate_source_and_backup(
    source: Path,
    backup: Path,
    expected_sha256: str,
    normalization_policy: LegacyNormalizationPolicy | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _validate_distinct_inputs(source, backup)
    inspection = inspect_source(source, normalization_policy)
    _raise_for_source_problems(inspection)
    if inspection["metadata_after"]["sha256"] != expected_sha256:
        raise ImporterError("Selected source does not match expected SHA-256")
    backup_evidence = _inspect_frozen_backup(
        backup, expected_sha256, normalization_policy
    )
    return inspection, backup_evidence


def _inspect_frozen_backup(
    backup: Path,
    expected_sha256: str,
    normalization_policy: LegacyNormalizationPolicy | None = None,
) -> dict[str, Any]:
    inspection = inspect_source(backup, normalization_policy)
    _raise_for_source_problems(inspection)
    if inspection["metadata_after"]["sha256"] != expected_sha256:
        raise ImporterError("Selected backup does not match expected frozen source")
    return {
        "metadata_before": inspection["metadata_before"],
        "metadata_after": inspection["metadata_after"],
        "unchanged": inspection["unchanged"],
        "schema_fingerprint_sha256": inspection["schema"]["fingerprint_sha256"],
    }


def _validate_artifacts_against_inputs(
    *,
    inspection: Mapping[str, Any],
    backup_metadata: Mapping[str, Any] | None,
    owner_map: Mapping[str, Any],
    normalization_policy: LegacyNormalizationPolicy | None,
    mapping: Mapping[str, Any],
    mapping_file_checksum: str,
    plan: Mapping[str, Any],
) -> None:
    if plan.get("namespace") != str(LEGACY_IMPORT_NAMESPACE):
        raise ImporterError("Approved plan uses an unexpected import namespace")
    if mapping.get("namespace") != str(LEGACY_IMPORT_NAMESPACE):
        raise ImporterError("Identity mapping uses an unexpected import namespace")
    if plan.get("identity_mapping_file_sha256") != mapping_file_checksum:
        raise ImporterError("Identity mapping file does not match the approved plan")
    if plan.get("source", {}).get("metadata") != inspection["metadata_after"]:
        raise ImporterError("Source does not match the approved plan")
    if (
        plan.get("source", {}).get("schema_fingerprint_sha256")
        != inspection["schema"]["fingerprint_sha256"]
    ):
        raise ImporterError("Source schema does not match the approved plan")
    if plan.get("source", {}).get("statistics") != inspection["statistics"]:
        raise ImporterError("Source statistics do not match the approved plan")
    expected_normalization = inspection.get("normalization")
    plan_source = plan.get("source", {})
    if normalization_policy is None:
        if "normalization" in plan_source:
            raise ImporterError(
                "Approved plan unexpectedly requires source normalization"
            )
    elif plan_source.get("normalization") != expected_normalization:
        raise ImporterError("Source normalization does not match the approved plan")
    if mapping.get("source_sha256") != inspection["metadata_after"]["sha256"]:
        raise ImporterError("Identity mapping does not match the selected source")
    if plan.get("owner_map", {}).get("file_sha256") != owner_map["file_sha256"]:
        raise ImporterError("Owner map file does not match the approved plan")
    if mapping.get("owner_map", {}).get("file_sha256") != owner_map["file_sha256"]:
        raise ImporterError("Owner map file does not match the identity mapping")
    if plan.get("owner_map", {}).get("groups") != owner_map["groups"]:
        raise ImporterError("Owner assignments do not match the approved plan")
    if mapping.get("owner_map", {}).get("groups") != owner_map["groups"]:
        raise ImporterError("Owner assignments do not match the identity mapping")
    for artifact in (mapping, plan):
        artifact_owner_map = artifact.get("owner_map", {})
        if (
            artifact_owner_map.get("version") != owner_map["version"]
            or artifact_owner_map.get("canonical_sha256")
            != owner_map["canonical_sha256"]
        ):
            raise ImporterError("Owner map contract does not match approved artifacts")
    expected_policy = (
        normalization_policy.artifact_evidence()
        if normalization_policy is not None
        else None
    )
    for artifact in (mapping, plan):
        if normalization_policy is None:
            if "normalization_policy" in artifact:
                raise ImporterError(
                    "Approved artifacts require an explicit normalization policy"
                )
        elif artifact.get("normalization_policy") != expected_policy:
            raise ImporterError(
                "Normalization policy does not match the approved artifacts"
            )
    if plan.get("imported_at") != mapping.get("imported_at"):
        raise ImporterError("Plan and identity mapping timestamps do not match")
    if plan.get("checksums") != mapping.get("checksums"):
        raise ImporterError("Plan and identity mapping checksums do not match")
    if backup_metadata is not None:
        if plan.get("backup") != backup_metadata:
            raise ImporterError("Backup does not match the approved plan")


def _verify_plan_internal_consistency(plan: Mapping[str, Any]) -> None:
    rows = plan.get("rows")
    logical_facts = plan.get("logical_facts")
    projections = plan.get("compatibility_projections")
    if not isinstance(rows, dict) or set(rows) != set(DOMAIN_TABLE_NAMES):
        raise ImporterError("Approved plan has an invalid row set")
    if not isinstance(logical_facts, list) or not isinstance(projections, list):
        raise ImporterError("Approved plan has invalid logical projections")
    if any(not isinstance(rows[table], list) for table in DOMAIN_TABLE_NAMES):
        raise ImporterError("Approved plan table rows must be JSON arrays")
    recalculated = _checksum_bundle(rows, logical_facts, projections)
    if plan.get("checksums") != recalculated:
        raise ImporterError("Approved plan row or projection checksums are invalid")
    expected_counts = {
        table_name: len(rows[table_name]) for table_name in DOMAIN_TABLE_NAMES
    }
    if plan.get("expected_counts") != expected_counts:
        raise ImporterError("Approved plan row counts are invalid")


def _verify_approved_contract(
    *,
    inspection: Mapping[str, Any],
    owner_map: Mapping[str, Any],
    mapping: Mapping[str, Any],
    plan: Mapping[str, Any],
    normalization_policy: LegacyNormalizationPolicy | None = None,
) -> None:
    for artifact in (mapping, plan):
        if artifact.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
            raise ImporterError("Approved artifact schema version is unsupported")
        if artifact.get("tool_version") != TOOL_VERSION:
            raise ImporterError("Approved artifact tool version is unsupported")
        if artifact.get("legacy_contract_version") != LEGACY_CONTRACT_VERSION:
            raise ImporterError("Approved artifact legacy contract version is invalid")

    imported_at = _parse_datetime(str(plan.get("imported_at")))
    timestamp = _format_datetime(imported_at)
    if plan.get("imported_at") != timestamp or mapping.get("imported_at") != timestamp:
        raise ImporterError("Approved artifact import timestamp is not canonical")

    expected = _expected_import_state(
        list(inspection["logical_facts"]), owner_map["groups"], timestamp
    )
    logical_facts = expected["logical_facts"]
    status_contract = {
        "version": STATUS_MAP_VERSION,
        "legacy_to_domain": dict(LEGACY_TO_DOMAIN_STATUS),
        "domain_to_legacy": dict(DOMAIN_TO_LEGACY_STATUS),
    }
    expected_status_map = {
        **status_contract,
        "sha256": _sha256_json(status_contract),
    }
    expected_policy = (
        normalization_policy.artifact_evidence()
        if normalization_policy is not None
        else None
    )
    for artifact in (mapping, plan):
        if normalization_policy is None:
            if "normalization_policy" in artifact:
                raise ImporterError(
                    "Approved contract unexpectedly requires normalization"
                )
        elif artifact.get("normalization_policy") != expected_policy:
            raise ImporterError("Approved normalization policy evidence is invalid")

    if mapping.get("users") != expected["user_identities"]:
        raise ImporterError("Identity mapping user decisions are invalid")
    if mapping.get("groups") != expected["group_identities"]:
        raise ImporterError("Identity mapping group decisions are invalid")
    if mapping.get("memberships") != expected["rows"]["group_memberships"]:
        raise ImporterError("Identity mapping membership decisions are invalid")
    if mapping.get("status_map") != expected_status_map:
        raise ImporterError("Identity mapping status contract is invalid")
    if mapping.get("checksums") != expected["checksums"]:
        raise ImporterError("Identity mapping checksums do not match the contract")

    if plan.get("rows") != expected["rows"]:
        raise ImporterError("Approved plan rows do not match the frozen contract")
    if plan.get("logical_facts") != logical_facts:
        raise ImporterError("Approved plan facts do not match the selected source")
    if plan.get("compatibility_projections") != expected["projections"]:
        raise ImporterError("Approved plan compatibility projections are invalid")
    if plan.get("checksums") != expected["checksums"]:
        raise ImporterError("Approved plan checksums do not match the frozen contract")
    if plan.get("status_map") != expected_status_map:
        raise ImporterError("Approved plan status contract is invalid")
    if mapping.get("destination") != plan.get("destination"):
        raise ImporterError("Mapping and plan destinations do not match")


def _projection_state_from_snapshot(
    snapshot: Mapping[str, Sequence[dict[str, Any]]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    users = {row["id"]: row["display_name"] for row in snapshot["users"]}
    groups = {row["id"]: row["name"] for row in snapshot["groups"]}
    memberships_by_user: defaultdict[str, list[str]] = defaultdict(list)
    for membership in snapshot["group_memberships"]:
        group_name = groups.get(membership["group_id"])
        if group_name is not None:
            memberships_by_user[membership["user_id"]].append(group_name)

    logical_facts: list[dict[str, str]] = []
    projections: list[dict[str, str]] = []
    for availability in snapshot["availability"]:
        user_name = users.get(availability["user_id"])
        legacy_status = DOMAIN_TO_LEGACY_STATUS.get(str(availability["status"]))
        if user_name is None or legacy_status is None:
            continue
        logical_fact = {
            "user_name": str(user_name),
            "day": str(availability["day"]),
            "legacy_status": legacy_status,
            "status": str(availability["status"]),
        }
        logical_facts.append(logical_fact)
        for group_name in memberships_by_user[availability["user_id"]]:
            projections.append(
                {
                    "group_name": group_name,
                    "user_name": str(user_name),
                    "date": str(availability["day"]),
                    "status": legacy_status,
                }
            )
    return _sort_rows(logical_facts), _sort_rows(projections)


def _verify_snapshot(
    plan: Mapping[str, Any],
    snapshot: Mapping[str, Sequence[dict[str, Any]]],
) -> dict[str, Any]:
    expected_rows = plan["rows"]
    comparison = _compare_rows(expected_rows, snapshot)
    actual_logical, actual_projections = _projection_state_from_snapshot(snapshot)
    actual_checksums = _checksum_bundle(snapshot, actual_logical, actual_projections)
    checksum_mismatches = [
        key
        for key in (
            "tables",
            "logical_user_day_status_sha256",
            "per_user",
            "per_group_month_projection",
            "admin_range_projection",
            "aggregate_projection_sha256",
        )
        if actual_checksums.get(key) != plan["checksums"].get(key)
    ]
    logical_mismatch = actual_logical != plan["logical_facts"]
    projection_mismatch = actual_projections != plan["compatibility_projections"]
    total = (
        comparison["total_mismatch_count"]
        + len(checksum_mismatches)
        + int(logical_mismatch)
        + int(projection_mismatch)
    )
    return {
        **comparison,
        "checksum_mismatch_count": len(checksum_mismatches),
        "checksum_mismatch_categories": checksum_mismatches,
        "logical_fact_mismatch": logical_mismatch,
        "compatibility_projection_mismatch": projection_mismatch,
        "verification_mismatch_count": total,
        "actual_checksums": actual_checksums,
    }


def _acquire_advisory_lock(connection: Connection) -> None:
    connection.execute(
        sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": IMPORT_ADVISORY_LOCK_KEY},
    )


def _after_category_flushed(category: str, connection: Connection) -> None:
    """Test seam for deterministic transaction rollback assertions."""
    del category, connection


def _database_rows(
    table_name: str, rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    uuid_fields = {
        "users": {"id"},
        "groups": {"id"},
        "group_memberships": {"group_id", "user_id"},
        "availability": {"user_id"},
    }[table_name]
    datetime_fields = {
        "users": {"created_at", "updated_at"},
        "groups": {"created_at", "updated_at"},
        "group_memberships": {"joined_at"},
        "availability": {"updated_at"},
    }[table_name]
    for row in rows:
        database_row: dict[str, Any] = {}
        for key, value in row.items():
            if key in uuid_fields:
                database_row[key] = uuid.UUID(str(value))
            elif key in datetime_fields:
                database_row[key] = _parse_datetime(str(value))
            elif table_name == "availability" and key == "day":
                try:
                    database_row[key] = date.fromisoformat(str(value))
                except ValueError:
                    raise ImporterError(
                        "Approved plan contains an invalid date"
                    ) from None
            else:
                database_row[key] = value
        converted.append(database_row)
    return converted


def _insert_plan_rows(connection: Connection, plan: Mapping[str, Any]) -> None:
    tables = {
        "users": User.__table__,
        "groups": Group.__table__,
        "group_memberships": GroupMembership.__table__,
        "availability": Availability.__table__,
    }
    for table_name in DOMAIN_TABLE_NAMES:
        rows = plan["rows"][table_name]
        if rows:
            connection.execute(
                sa.insert(tables[table_name]),
                _database_rows(table_name, rows),
            )
        _after_category_flushed(table_name, connection)


def _safe_destination_read(
    destination: Destination,
    operation: Callable[[Connection], Any],
) -> Any:
    runtime, engine = _connect_engine(destination)
    try:
        try:
            with engine.connect() as connection:
                return operation(connection)
        except ImporterError:
            raise
        except Exception as exc:
            raise ImporterError(
                f"Could not read destination {destination.safe_url} ({type(exc).__name__})"
            ) from None
    finally:
        runtime.dispose()


def _prepare_source_inputs(
    source_raw: Path,
    backup_raw: Path | None,
    expected_sha256: str | None,
) -> tuple[Path, Path | None, str | None]:
    source = _resolve_input_file(source_raw, "Source SQLite")
    backup = (
        _resolve_input_file(backup_raw, "Backup SQLite")
        if backup_raw is not None
        else None
    )
    _validate_distinct_inputs(source, backup)
    expected = (
        _validate_expected_sha256(expected_sha256)
        if expected_sha256 is not None
        else None
    )
    return source, backup, expected


def _prepare_normalization_policy(
    raw_path: Path | None,
) -> tuple[Path | None, LegacyNormalizationPolicy | None]:
    if raw_path is None:
        return None, None
    path = _resolve_input_file(raw_path, "Normalization policy")
    return path, _load_normalization_policy(path)


def run_inspect(args: argparse.Namespace) -> None:
    started = _utc_now()
    source, _, _ = _prepare_source_inputs(args.source_sqlite, None, None)
    policy_path, normalization_policy = _prepare_normalization_policy(
        args.normalization_policy
    )
    inputs = (source,) if policy_path is None else (source, policy_path)
    (report_output,) = _preflight_output_paths(
        (args.report_output,),
        inputs=inputs,
    )
    inspection = inspect_source(source, normalization_policy)
    outcome = (
        "source_conflict"
        if inspection["conflicting_logical_facts"]
        else (
            "validation_failed"
            if inspection["schema_errors"] or inspection["validation_errors"]
            else "inspected"
        )
    )
    report = _report_header("inspect_report", started)
    report.update(
        {
            "source": inspection,
            "status_map": {
                "version": STATUS_MAP_VERSION,
                "sha256": _sha256_json(
                    {
                        "version": STATUS_MAP_VERSION,
                        "legacy_to_domain": dict(LEGACY_TO_DOMAIN_STATUS),
                        "domain_to_legacy": dict(DOMAIN_TO_LEGACY_STATUS),
                    }
                ),
            },
            "transaction_outcome": outcome,
        }
    )
    if normalization_policy is not None:
        report["normalization_policy"] = normalization_policy.artifact_evidence()
    _atomic_write_json(report_output, _finish_report(report, outcome))
    _raise_for_source_problems(inspection)
    print(
        f"inspect: valid synthetic source with "
        f"{inspection['statistics']['raw_row_count']} rows"
    )


def run_plan(args: argparse.Namespace) -> None:
    started = _utc_now()
    source, backup, expected = _prepare_source_inputs(
        args.source_sqlite,
        args.backup_sqlite,
        args.expected_source_sha256,
    )
    assert backup is not None and expected is not None
    owner_path = _resolve_input_file(args.owner_map, "Owner map")
    policy_path, normalization_policy = _prepare_normalization_policy(
        args.normalization_policy
    )
    input_paths = [source, backup, owner_path]
    if policy_path is not None:
        input_paths.append(policy_path)
    mapping_output, plan_output, report_output = _preflight_output_paths(
        (args.mapping_output, args.plan_output, args.report_output),
        inputs=tuple(input_paths),
    )
    inspection, backup_metadata = _validate_source_and_backup(
        source,
        backup,
        expected,
        normalization_policy,
    )
    owner_map = _load_owner_map(owner_path)
    destination = _resolve_destination(args.destination_url_env)
    imported_at = _utc_now()

    def inspect_destination(connection: Connection) -> dict[str, Any]:
        revision = _require_destination_revision(connection)
        mapping, plan = _build_expected_artifacts(
            inspection,
            owner_map,
            imported_at,
            destination,
            revision,
            backup_metadata,
            normalization_policy,
        )
        snapshot = _destination_snapshot(connection)
        classification, comparison = _classify_destination(plan["rows"], snapshot)
        return {
            "revision": revision,
            "mapping": mapping,
            "plan": plan,
            "classification": classification,
            "comparison": comparison,
        }

    result = _safe_destination_read(destination, inspect_destination)
    report = _report_header("plan_report", started)
    report.update(
        {
            "source": inspection,
            "backup": backup_metadata,
            "owner_map": {
                "version": owner_map["version"],
                "file_sha256": owner_map["file_sha256"],
                "canonical_sha256": owner_map["canonical_sha256"],
            },
            "destination": {
                "environment_variable": destination.environment_name,
                "url": destination.safe_url,
                "alembic_revision": result["revision"],
                "classification": result["classification"],
            },
            "destination_comparison": result["comparison"],
            "planned_counts": result["plan"]["expected_counts"],
            "status_map": result["plan"]["status_map"],
            "checksums": result["plan"]["checksums"],
            "artifacts": {
                "identity_mapping_sha256": _sha256_bytes(
                    _json_file_bytes(result["mapping"])
                ),
                "import_plan_sha256": _sha256_bytes(_json_file_bytes(result["plan"])),
            },
        }
    )
    if normalization_policy is not None:
        report["normalization_policy"] = normalization_policy.artifact_evidence()
    if result["classification"] == "unsafe_nonempty":
        _atomic_write_json(report_output, _finish_report(report, "unsafe_nonempty"))
        raise UnsafeDestinationError("Destination contains nonmatching domain data")
    _atomic_write_json(mapping_output, result["mapping"])
    _atomic_write_json(plan_output, result["plan"])
    _atomic_write_json(report_output, _finish_report(report, "dry_run"))
    print(
        f"plan: dry run approved for {destination.safe_url}; "
        f"destination={result['classification']}"
    )


def _load_apply_or_verify_inputs(
    args: argparse.Namespace,
    *,
    require_backup: bool,
) -> dict[str, Any]:
    source, backup, expected = _prepare_source_inputs(
        args.source_sqlite,
        args.backup_sqlite if require_backup else None,
        args.expected_source_sha256,
    )
    assert expected is not None
    owner_path = _resolve_input_file(args.owner_map, "Owner map")
    policy_path, normalization_policy = _prepare_normalization_policy(
        args.normalization_policy
    )
    mapping_path = _resolve_input_file(args.mapping, "Identity mapping")
    plan_path = _resolve_input_file(args.approved_plan, "Approved plan")
    inputs = [source, owner_path, mapping_path, plan_path]
    if backup is not None:
        inputs.append(backup)
    if policy_path is not None:
        inputs.append(policy_path)
    (report_output,) = _preflight_output_paths(
        (args.report_output,),
        inputs=tuple(inputs),
    )
    inspection = inspect_source(source, normalization_policy)
    _raise_for_source_problems(inspection)
    if inspection["metadata_after"]["sha256"] != expected:
        raise ImporterError("Selected source does not match expected SHA-256")
    backup_metadata = (
        _inspect_frozen_backup(backup, expected, normalization_policy)
        if backup is not None
        else None
    )
    owner_map = _load_owner_map(owner_path)
    mapping, mapping_file_checksum = _load_artifact(
        mapping_path,
        "identity_mapping",
    )
    plan, plan_file_checksum = _load_artifact(plan_path, "import_plan")
    _verify_plan_internal_consistency(plan)
    _validate_artifacts_against_inputs(
        inspection=inspection,
        backup_metadata=backup_metadata,
        owner_map=owner_map,
        normalization_policy=normalization_policy,
        mapping=mapping,
        mapping_file_checksum=mapping_file_checksum,
        plan=plan,
    )
    _verify_approved_contract(
        inspection=inspection,
        owner_map=owner_map,
        mapping=mapping,
        plan=plan,
        normalization_policy=normalization_policy,
    )
    destination = _resolve_destination(args.destination_url_env)
    if plan.get("destination", {}).get("url") != destination.safe_url:
        raise ImporterError("Destination does not match the approved plan")
    return {
        "source": source,
        "backup": backup,
        "inspection": inspection,
        "backup_metadata": backup_metadata,
        "owner_map": owner_map,
        "normalization_policy": normalization_policy,
        "mapping": mapping,
        "mapping_file_checksum": mapping_file_checksum,
        "plan": plan,
        "plan_file_checksum": plan_file_checksum,
        "destination": destination,
        "report_output": report_output,
    }


def _independent_destination_verification(
    engine: Engine,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        with engine.connect() as raw_connection:
            connection = raw_connection.execution_options(
                isolation_level="REPEATABLE READ"
            )
            transaction = connection.begin()
            try:
                connection.execute(sa.text("SET TRANSACTION READ ONLY"))
                revision = _require_destination_revision(connection)
                snapshot = _destination_snapshot(connection)
                result = _verify_snapshot(plan, snapshot)
                result["alembic_revision"] = revision
                return result
            finally:
                if transaction.is_active:
                    transaction.rollback()
    except ImporterError:
        raise
    except Exception as exc:
        raise VerificationError(
            f"Independent destination verification failed ({type(exc).__name__})"
        ) from None


def _build_apply_report(
    *,
    started: datetime,
    inputs: Mapping[str, Any],
    destination: Destination,
    plan: Mapping[str, Any],
    outcome: str,
    classification_details: Mapping[str, Any],
    error: ImporterError | None = None,
) -> dict[str, Any]:
    report = _report_header("apply_report", started)
    report.update(
        {
            "source": inputs["inspection"],
            "backup": inputs["backup_metadata"],
            "destination": {
                "environment_variable": destination.environment_name,
                "url": destination.safe_url,
                "alembic_revision": plan["destination"]["alembic_revision"],
                "classification": outcome,
            },
            "destination_comparison": dict(classification_details),
            "planned_counts": plan["expected_counts"],
            "status_map": plan["status_map"],
            "owner_map": plan["owner_map"],
            "checksums": plan["checksums"],
            "artifacts": {
                "identity_mapping_file_sha256": inputs["mapping_file_checksum"],
                "approved_plan_file_sha256": inputs["plan_file_checksum"],
            },
            "imported_counts": (
                plan["expected_counts"]
                if outcome == "applied"
                else {table: 0 for table in DOMAIN_TABLE_NAMES}
            ),
            "matched_counts": (
                plan["expected_counts"]
                if outcome == "already_applied"
                else {table: 0 for table in DOMAIN_TABLE_NAMES}
            ),
            "skipped_counts": (
                plan["expected_counts"]
                if outcome == "already_applied"
                else {table: 0 for table in DOMAIN_TABLE_NAMES}
            ),
        }
    )
    if error is not None:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    if "normalization_policy" in plan:
        report["normalization_policy"] = plan["normalization_policy"]
    return report


def run_apply(args: argparse.Namespace) -> None:
    if not args.apply:
        raise ImporterError("apply requires the literal --apply safety switch")
    started = _utc_now()
    inputs = _load_apply_or_verify_inputs(args, require_backup=True)
    destination: Destination = inputs["destination"]
    plan: dict[str, Any] = inputs["plan"]
    try:
        runtime, engine = _connect_engine(destination)
    except Exception as exc:
        error = DatabaseWriteError(
            f"Could not configure import destination ({type(exc).__name__})"
        )
        report = _build_apply_report(
            started=started,
            inputs=inputs,
            destination=destination,
            plan=plan,
            outcome="transaction_failed",
            classification_details={},
            error=error,
        )
        _atomic_write_json(
            inputs["report_output"], _finish_report(report, "transaction_failed")
        )
        raise error from None

    outcome: str | None = None
    classification_details: dict[str, Any] = {}
    committed = False
    connection: Connection | None = None
    transaction: Any = None
    try:
        try:
            connection = engine.connect().execution_options(
                isolation_level="SERIALIZABLE"
            )
            transaction = connection.begin()
            revision = _require_destination_revision(connection)
            if revision != plan["destination"]["alembic_revision"]:
                raise ImporterError("Destination revision differs from approved plan")
            _acquire_advisory_lock(connection)
            snapshot = _destination_snapshot(connection)
            classification, classification_details = _classify_destination(
                plan["rows"], snapshot
            )
            if classification == "unsafe_nonempty":
                transaction.rollback()
                outcome = "unsafe_nonempty"
            elif classification == "exact_prior_import":
                transaction.rollback()
                outcome = "already_applied"
            else:
                _insert_plan_rows(connection, plan)
                internal_snapshot = _destination_snapshot(connection)
                internal_verification = _verify_snapshot(plan, internal_snapshot)
                if internal_verification["verification_mismatch_count"]:
                    classification_details = {
                        **classification_details,
                        "precommit_verification": internal_verification,
                    }
                    raise DatabaseWriteError(
                        "Pre-commit destination verification detected mismatches"
                    )
                transaction.commit()
                committed = True
                outcome = "applied"
        except Exception as exc:
            rolled_back = False
            if transaction is not None and transaction.is_active:
                try:
                    transaction.rollback()
                    rolled_back = True
                except Exception:
                    rolled_back = False
            error = (
                exc
                if isinstance(exc, ImporterError)
                else DatabaseWriteError(
                    f"Import transaction failed ({type(exc).__name__})"
                )
            )
            failure_outcome = "rolled_back" if rolled_back else "transaction_failed"
            report = _build_apply_report(
                started=started,
                inputs=inputs,
                destination=destination,
                plan=plan,
                outcome=failure_outcome,
                classification_details=classification_details,
                error=error,
            )
            try:
                _atomic_write_json(
                    inputs["report_output"],
                    _finish_report(report, failure_outcome),
                )
            except ImporterError:
                print(
                    "warning: transaction failure report publication failed",
                    file=sys.stderr,
                )
            raise error from None
        finally:
            if connection is not None:
                connection.close()

        assert outcome is not None
        report = _build_apply_report(
            started=started,
            inputs=inputs,
            destination=destination,
            plan=plan,
            outcome=outcome,
            classification_details=classification_details,
        )
        if outcome == "unsafe_nonempty":
            _atomic_write_json(
                inputs["report_output"],
                _finish_report(report, "unsafe_nonempty"),
            )
            raise UnsafeDestinationError("Destination contains nonmatching domain data")

        try:
            verification = _independent_destination_verification(engine, plan)
        except ImporterError as exc:
            report["independent_verification"] = {
                "verification_mismatch_count": 1,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            try:
                _atomic_write_json(
                    inputs["report_output"],
                    _finish_report(report, "verification_failed"),
                )
            except ImporterError:
                if committed:
                    raise VerificationError(
                        "Import committed but verification report publication failed"
                    ) from None
            raise VerificationError(
                "Post-import independent verification failed"
            ) from None
        report["independent_verification"] = verification
        if verification["verification_mismatch_count"]:
            _atomic_write_json(
                inputs["report_output"],
                _finish_report(report, "verification_failed"),
            )
            raise VerificationError("Post-import verification detected mismatches")
        try:
            _atomic_write_json(
                inputs["report_output"],
                _finish_report(report, outcome),
            )
        except ImporterError:
            if committed:
                raise VerificationError(
                    "Import committed but apply report publication failed"
                ) from None
            raise
        print(f"apply: {outcome} on {destination.safe_url}")
    finally:
        runtime.dispose()


def run_verify(args: argparse.Namespace) -> None:
    started = _utc_now()
    inputs = _load_apply_or_verify_inputs(args, require_backup=False)
    destination: Destination = inputs["destination"]
    plan: dict[str, Any] = inputs["plan"]
    runtime, engine = _connect_engine(destination)
    try:
        verification = _independent_destination_verification(engine, plan)
    finally:
        runtime.dispose()
    report = _report_header("verification_report", started)
    report.update(
        {
            "source": inputs["inspection"],
            "destination": {
                "environment_variable": destination.environment_name,
                "url": destination.safe_url,
                "alembic_revision": verification["alembic_revision"],
            },
            "verification": verification,
            "expected_counts": plan["expected_counts"],
            "status_map": plan["status_map"],
            "owner_map": plan["owner_map"],
            "checksums": plan["checksums"],
            "artifacts": {
                "identity_mapping_file_sha256": inputs["mapping_file_checksum"],
                "approved_plan_file_sha256": inputs["plan_file_checksum"],
            },
        }
    )
    if "normalization_policy" in plan:
        report["normalization_policy"] = plan["normalization_policy"]
    if verification["verification_mismatch_count"]:
        _atomic_write_json(
            inputs["report_output"],
            _finish_report(report, "verification_failed"),
        )
        raise VerificationError("Destination does not match the approved plan")
    _atomic_write_json(
        inputs["report_output"],
        _finish_report(report, "verified"),
    )
    print(f"verify: exact match on {destination.safe_url}")


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(
        prog="python -m backend.cli.import_legacy_sqlite",
        description="Inspect and import one explicitly selected legacy SQLite source.",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=SafeArgumentParser,
    )

    def add_normalization_policy(parser_to_extend: argparse.ArgumentParser) -> None:
        parser_to_extend.add_argument(
            "--normalization-policy",
            type=Path,
            help="Explicit versioned legacy normalization policy JSON file.",
        )

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--source-sqlite", type=Path, required=True)
    add_normalization_policy(inspect_parser)
    inspect_parser.add_argument("--report-output", type=Path, required=True)
    inspect_parser.set_defaults(handler=run_inspect)

    def add_source(parser_to_extend: argparse.ArgumentParser) -> None:
        parser_to_extend.add_argument("--source-sqlite", type=Path, required=True)
        parser_to_extend.add_argument(
            "--expected-source-sha256",
            required=True,
        )

    def add_destination(parser_to_extend: argparse.ArgumentParser) -> None:
        parser_to_extend.add_argument(
            "--destination-url-env",
            required=True,
            help="Exact environment variable containing the PostgreSQL URL.",
        )

    def add_approved_artifacts(parser_to_extend: argparse.ArgumentParser) -> None:
        parser_to_extend.add_argument("--owner-map", type=Path, required=True)
        parser_to_extend.add_argument("--mapping", type=Path, required=True)
        parser_to_extend.add_argument("--approved-plan", type=Path, required=True)
        parser_to_extend.add_argument("--report-output", type=Path, required=True)

    plan_parser = subparsers.add_parser("plan")
    add_source(plan_parser)
    add_normalization_policy(plan_parser)
    plan_parser.add_argument("--backup-sqlite", type=Path, required=True)
    add_destination(plan_parser)
    plan_parser.add_argument("--owner-map", type=Path, required=True)
    plan_parser.add_argument("--mapping-output", type=Path, required=True)
    plan_parser.add_argument("--plan-output", type=Path, required=True)
    plan_parser.add_argument("--report-output", type=Path, required=True)
    plan_parser.set_defaults(handler=run_plan)

    apply_parser = subparsers.add_parser("apply")
    add_source(apply_parser)
    add_normalization_policy(apply_parser)
    apply_parser.add_argument("--backup-sqlite", type=Path, required=True)
    add_destination(apply_parser)
    add_approved_artifacts(apply_parser)
    apply_parser.add_argument("--apply", action="store_true")
    apply_parser.set_defaults(handler=run_apply)

    verify_parser = subparsers.add_parser("verify")
    add_source(verify_parser)
    add_normalization_policy(verify_parser)
    add_destination(verify_parser)
    add_approved_artifacts(verify_parser)
    verify_parser.set_defaults(handler=run_verify)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = build_parser().parse_args(argv)
        arguments.handler(arguments)
        return int(ExitCode.SUCCESS)
    except ImporterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return int(exc.exit_code)
    except KeyboardInterrupt:
        print("error: importer interrupted", file=sys.stderr)
        return int(ExitCode.COMMAND_OR_VALIDATION_ERROR)
    except Exception as exc:
        print(
            f"error: unexpected importer failure ({type(exc).__name__})",
            file=sys.stderr,
        )
        return int(ExitCode.COMMAND_OR_VALIDATION_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
