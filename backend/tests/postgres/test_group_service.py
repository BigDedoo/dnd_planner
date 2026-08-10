from __future__ import annotations

from collections.abc import Callable

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.group_service import (
    GroupNotFoundError,
    MembershipNotFoundError,
    OwnerInvariantError,
    create_group_with_owner,
    delete_group,
    remove_member,
    transfer_ownership,
)
from backend.models import Group, GroupMembership, MembershipRole, User


def _create_user(session: Session, name: str) -> User:
    user = User(display_name=name)
    session.add(user)
    session.flush()
    return user


def _owner_count(session: Session, group_id: object) -> int:
    return session.scalar(
        sa.select(sa.func.count())
        .select_from(GroupMembership)
        .where(
            GroupMembership.group_id == group_id,
            GroupMembership.role == MembershipRole.OWNER,
        )
    )


def test_create_group_commits_exactly_one_owner_and_two_groups_are_independent(
    db_session: Session,
) -> None:
    with db_session.begin():
        first_owner = _create_user(db_session, "First owner")
        second_owner = _create_user(db_session, "Second owner")

    with db_session.begin():
        first_group = create_group_with_owner(
            db_session,
            name="First group",
            owner_user_id=first_owner.id,
        )
        second_group = create_group_with_owner(
            db_session,
            name="Second group",
            owner_user_id=second_owner.id,
        )

    with db_session.begin():
        assert _owner_count(db_session, first_group.id) == 1
        assert _owner_count(db_session, second_group.id) == 1


def test_partial_index_rejects_a_second_owner(db_session: Session) -> None:
    with db_session.begin():
        owner = _create_user(db_session, "Owner")
        member = _create_user(db_session, "Member")
    with db_session.begin():
        group = create_group_with_owner(
            db_session,
            name="Group",
            owner_user_id=owner.id,
        )
        db_session.add(
            GroupMembership(
                group_id=group.id,
                user_id=member.id,
                role=MembershipRole.MEMBER,
                display_order=1,
            )
        )

    with pytest.raises(IntegrityError):
        with db_session.begin():
            membership = db_session.get(GroupMembership, (group.id, member.id))
            assert membership is not None
            membership.role = MembershipRole.OWNER
            db_session.flush()

    with db_session.begin():
        assert _owner_count(db_session, group.id) == 1


def test_transfer_ownership_is_atomic_and_demotes_old_owner(
    db_session: Session,
) -> None:
    with db_session.begin():
        old_owner = _create_user(db_session, "Old owner")
        new_owner = _create_user(db_session, "New owner")
    with db_session.begin():
        group = create_group_with_owner(
            db_session,
            name="Group",
            owner_user_id=old_owner.id,
        )
        db_session.add(
            GroupMembership(
                group_id=group.id,
                user_id=new_owner.id,
                role=MembershipRole.ORGANIZER,
                display_order=1,
            )
        )

    with db_session.begin():
        transfer_ownership(
            db_session,
            group_id=group.id,
            current_owner_user_id=old_owner.id,
            new_owner_user_id=new_owner.id,
        )

    with db_session.begin():
        old_membership = db_session.get(GroupMembership, (group.id, old_owner.id))
        new_membership = db_session.get(GroupMembership, (group.id, new_owner.id))
        assert old_membership is not None
        assert new_membership is not None
        assert old_membership.role == MembershipRole.MEMBER
        assert new_membership.role == MembershipRole.OWNER
        assert _owner_count(db_session, group.id) == 1


def test_invalid_transfers_are_rejected(db_session: Session) -> None:
    with db_session.begin():
        owner = _create_user(db_session, "Owner")
        member = _create_user(db_session, "Member")
        outsider = _create_user(db_session, "Outsider")
    with db_session.begin():
        group = create_group_with_owner(
            db_session,
            name="Group",
            owner_user_id=owner.id,
        )
        db_session.add(
            GroupMembership(
                group_id=group.id,
                user_id=member.id,
                role=MembershipRole.MEMBER,
                display_order=1,
            )
        )

    with pytest.raises(MembershipNotFoundError):
        with db_session.begin():
            transfer_ownership(
                db_session,
                group_id=group.id,
                current_owner_user_id=owner.id,
                new_owner_user_id=outsider.id,
            )

    with pytest.raises(OwnerInvariantError):
        with db_session.begin():
            transfer_ownership(
                db_session,
                group_id=group.id,
                current_owner_user_id=member.id,
                new_owner_user_id=owner.id,
            )

    with pytest.raises(GroupNotFoundError):
        with db_session.begin():
            transfer_ownership(
                db_session,
                group_id=outsider.id,
                current_owner_user_id=owner.id,
                new_owner_user_id=member.id,
            )


def test_remove_nonowner_reject_owner_and_delete_group(db_session: Session) -> None:
    with db_session.begin():
        owner = _create_user(db_session, "Owner")
        member = _create_user(db_session, "Member")
    with db_session.begin():
        group = create_group_with_owner(
            db_session,
            name="Group",
            owner_user_id=owner.id,
        )
        db_session.add(
            GroupMembership(
                group_id=group.id,
                user_id=member.id,
                role=MembershipRole.MEMBER,
                display_order=1,
            )
        )

    with db_session.begin():
        remove_member(db_session, group_id=group.id, user_id=member.id)
    with db_session.begin():
        assert db_session.get(GroupMembership, (group.id, member.id)) is None
        assert _owner_count(db_session, group.id) == 1

    with pytest.raises(OwnerInvariantError):
        with db_session.begin():
            remove_member(db_session, group_id=group.id, user_id=owner.id)

    with db_session.begin():
        assert _owner_count(db_session, group.id) == 1
    with db_session.begin():
        delete_group(db_session, group_id=group.id)
    with db_session.begin():
        assert db_session.get(Group, group.id) is None
        assert (
            db_session.scalar(
                sa.select(sa.func.count())
                .select_from(GroupMembership)
                .where(GroupMembership.group_id == group.id)
            )
            == 0
        )


def test_injected_transfer_failure_rolls_back_original_owner(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with db_session.begin():
        old_owner = _create_user(db_session, "Old owner")
        new_owner = _create_user(db_session, "New owner")
    with db_session.begin():
        group = create_group_with_owner(
            db_session,
            name="Group",
            owner_user_id=old_owner.id,
        )
        db_session.add(
            GroupMembership(
                group_id=group.id,
                user_id=new_owner.id,
                role=MembershipRole.MEMBER,
                display_order=1,
            )
        )

    real_flush: Callable[..., None] = db_session.flush
    flush_count = 0

    def fail_second_flush(*args: object, **kwargs: object) -> None:
        nonlocal flush_count
        flush_count += 1
        if flush_count == 2:
            raise RuntimeError("injected transfer failure")
        real_flush(*args, **kwargs)

    with monkeypatch.context() as patch_context:
        patch_context.setattr(db_session, "flush", fail_second_flush)
        with pytest.raises(RuntimeError, match="injected transfer failure"):
            with db_session.begin():
                transfer_ownership(
                    db_session,
                    group_id=group.id,
                    current_owner_user_id=old_owner.id,
                    new_owner_user_id=new_owner.id,
                )

    db_session.expire_all()
    with db_session.begin():
        old_membership = db_session.get(GroupMembership, (group.id, old_owner.id))
        new_membership = db_session.get(GroupMembership, (group.id, new_owner.id))
        assert old_membership is not None
        assert new_membership is not None
        assert old_membership.role == MembershipRole.OWNER
        assert new_membership.role == MembershipRole.MEMBER
        assert _owner_count(db_session, group.id) == 1
