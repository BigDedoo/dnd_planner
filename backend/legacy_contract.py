"""Immutable legacy identities, ordering, and status translations.

The current SQLite runtime and the Phase 1B importer share this contract.  It
contains no owner assignments and no data discovered from a SQLite file.
"""

from __future__ import annotations

import unicodedata
import uuid
from types import MappingProxyType
from typing import Literal, Mapping

LEGACY_CONTRACT_VERSION = 1
STATUS_MAP_VERSION = 1
LEGACY_IMPORT_NAMESPACE = uuid.UUID("b47e7a21-6b6f-4c5d-a3d2-193b02d77d6f")

_GROUPS = {
    "Green flag": ("Quentin", "Arnaud", "Ulrich", "Daerrus", "Dembe"),
    "1D6": ("Gaelle", "Rico", "Yoann", "Romane", "Victor", "Dembe"),
    "Underdark": ("Dembe", "Arnaud", "Quentin", "Martin", "Baptiste"),
}
GROUPS: Mapping[str, tuple[str, ...]] = MappingProxyType(_GROUPS)


def _ordered_distinct_users() -> tuple[str, ...]:
    return tuple(dict.fromkeys(user for users in GROUPS.values() for user in users))


LEGACY_USERS = _ordered_distinct_users()

LEGACY_TO_DOMAIN_STATUS: Mapping[str, str] = MappingProxyType(
    {
        "Available": "available",
        "Maybe": "maybe",
        "No": "unavailable",
    }
)
DOMAIN_TO_LEGACY_STATUS: Mapping[str, str] = MappingProxyType(
    {value: key for key, value in LEGACY_TO_DOMAIN_STATUS.items()}
)

IdentityKind = Literal["user", "group"]


def canonical_legacy_identity(kind: IdentityKind, value: str) -> str:
    """Return the exact UUIDv5 name after NFC normalization only."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Legacy identity values must be nonblank strings")
    if kind not in {"user", "group"}:
        raise ValueError("Legacy identity kind must be user or group")
    return f"{kind}\0{unicodedata.normalize('NFC', value)}"


def deterministic_legacy_uuid(kind: IdentityKind, value: str) -> uuid.UUID:
    """Derive the approved deterministic UUIDv5 for one legacy identity."""
    return uuid.uuid5(
        LEGACY_IMPORT_NAMESPACE,
        canonical_legacy_identity(kind, value),
    )


def assert_no_nfc_collisions(kind: IdentityKind, values: tuple[str, ...]) -> None:
    """Reject distinct source identities that collapse to one NFC key."""
    originals_by_key: dict[str, str] = {}
    for value in values:
        canonical = canonical_legacy_identity(kind, value)
        previous = originals_by_key.setdefault(canonical, value)
        if previous != value:
            raise ValueError(
                f"Distinct legacy {kind} values normalize to the same NFC identity"
            )
