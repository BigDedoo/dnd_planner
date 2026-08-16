"""Small, dependency-free helpers for group invite codes."""

from __future__ import annotations

import hashlib
import re
import secrets
import time
import uuid
from collections import defaultdict, deque

INVITE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
INVITE_CODE_LENGTH = 8
INVITE_JOIN_MAX_FAILURES = 5
INVITE_JOIN_WINDOW_SECONDS = 60


def normalize_invite_code(value: str) -> str:
    """Accept case-insensitive codes with optional separators and spaces."""
    return re.sub(r"[-\s]", "", value).upper()


def format_invite_code(value: str) -> str:
    normalized = normalize_invite_code(value)
    return f"{normalized[:4]}-{normalized[4:]}"


def generate_invite_code() -> str:
    raw_code = "".join(
        secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH)
    )
    return format_invite_code(raw_code)


def hash_invite_code(value: str) -> str:
    return hashlib.sha256(normalize_invite_code(value).encode("ascii")).hexdigest()


class InviteJoinRateLimiter:
    """Bound failed code guesses per authenticated DnD user in one process."""

    def __init__(self) -> None:
        self._failures: dict[uuid.UUID, deque[float]] = defaultdict(deque)

    def allow_attempt(self, user_id: uuid.UUID) -> bool:
        now = time.monotonic()
        failures = self._failures[user_id]
        while failures and failures[0] <= now - INVITE_JOIN_WINDOW_SECONDS:
            failures.popleft()
        return len(failures) < INVITE_JOIN_MAX_FAILURES

    def record_failure(self, user_id: uuid.UUID) -> None:
        self._failures[user_id].append(time.monotonic())

    def clear(self, user_id: uuid.UUID) -> None:
        self._failures.pop(user_id, None)
