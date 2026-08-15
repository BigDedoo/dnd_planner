from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from backend.auth import resolve_or_provision_account
from backend.models import Account, AccountIdentity


def test_account_creation_and_identity_relationship(db_session: Session) -> None:
    account = Account(
        id=uuid.uuid4(),
        email="adventurer@example.com",
        display_name="Bold Fighter",
    )
    db_session.add(account)
    db_session.flush()

    identity = AccountIdentity(
        id=uuid.uuid4(),
        account_id=account.id,
        provider="clerk",
        provider_subject="user_2abcdef123456",
    )
    db_session.add(identity)
    db_session.commit()

    retrieved = db_session.get(Account, account.id)
    assert retrieved is not None
    assert retrieved.email == "adventurer@example.com"
    assert retrieved.display_name == "Bold Fighter"
    assert len(retrieved.identities) == 1
    assert retrieved.identities[0].provider == "clerk"
    assert retrieved.identities[0].provider_subject == "user_2abcdef123456"


def test_account_identity_unique_constraint(db_session: Session) -> None:
    account1 = Account(id=uuid.uuid4(), email="user1@example.com")
    account2 = Account(id=uuid.uuid4(), email="user2@example.com")
    db_session.add_all([account1, account2])
    db_session.flush()

    identity1 = AccountIdentity(
        id=uuid.uuid4(),
        account_id=account1.id,
        provider="clerk",
        provider_subject="user_shared_subject",
    )
    db_session.add(identity1)
    db_session.commit()

    # Attempting to assign same (provider, provider_subject) to account2 should fail
    identity2 = AccountIdentity(
        id=uuid.uuid4(),
        account_id=account2.id,
        provider="clerk",
        provider_subject="user_shared_subject",
    )
    db_session.add(identity2)
    with pytest.raises(sa.exc.IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_account_cascade_delete_removes_identities(db_session: Session) -> None:
    account = Account(id=uuid.uuid4(), email="cascade@example.com")
    db_session.add(account)
    db_session.flush()

    identity = AccountIdentity(
        id=uuid.uuid4(),
        account_id=account.id,
        provider="clerk",
        provider_subject="user_cascade_subject",
    )
    db_session.add(identity)
    db_session.commit()
    identity_id = identity.id

    # Delete account
    db_session.delete(account)
    db_session.commit()
    db_session.expire_all()

    # Identity must be cascade-deleted
    assert db_session.get(AccountIdentity, identity_id) is None


def test_concurrent_account_provisioning(postgres_engine: sa.Engine) -> None:
    """Simulate concurrent requests from the same Clerk user resolving the same account."""
    subject = f"user_concurrent_{uuid.uuid4().hex[:8]}"

    def provision_worker() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            account = resolve_or_provision_account(
                session=session,
                provider="clerk",
                provider_subject=subject,
                email="concurrent@example.com",
            )
            return str(account.id)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(provision_worker) for _ in range(5)]
        results = [f.result() for f in futures]

    # All concurrent requests must resolve to the same account ID
    assert len(set(results)) == 1
    with Session(postgres_engine) as session:
        identities = (
            session.query(AccountIdentity)
            .filter_by(provider="clerk", provider_subject=subject)
            .all()
        )
        assert len(identities) == 1
