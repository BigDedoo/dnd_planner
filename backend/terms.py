"""Versioned public Terms document and account-level acceptance contract."""

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .models import Account

CURRENT_TERMS_VERSION: str = json.loads(
    Path(__file__).with_name("terms.json").read_text(encoding="utf-8")
)["version"]


class TermsStatus(BaseModel):
    current_terms_version: str
    terms_accepted: bool
    terms_version: str | None = None
    terms_accepted_at: datetime | None = None


class TermsAcceptance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    terms_version: str


def has_current_terms(account: Account) -> bool:
    return (
        account.terms_version == CURRENT_TERMS_VERSION
        and account.terms_accepted_at is not None
    )


def terms_status(account: Account) -> dict:
    return TermsStatus(
        current_terms_version=CURRENT_TERMS_VERSION,
        terms_accepted=has_current_terms(account),
        terms_version=account.terms_version,
        terms_accepted_at=account.terms_accepted_at,
    ).model_dump()
