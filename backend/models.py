from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


class MembershipRole(StrEnum):
    OWNER = "owner"
    ORGANIZER = "organizer"
    MEMBER = "member"


class AvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    MAYBE = "maybe"
    UNAVAILABLE = "unavailable"


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


membership_role_type = sa.Enum(
    MembershipRole,
    name="membership_role",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=_enum_values,
    length=16,
)

availability_status_type = sa.Enum(
    AvailabilityStatus,
    name="availability_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=_enum_values,
    length=16,
)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        sa.CheckConstraint(
            "btrim(display_name) <> ''",
            name="ck_users_display_name_not_blank",
        ),
        sa.CheckConstraint(
            "(auth_provider IS NULL AND auth_subject IS NULL) OR "
            "(auth_provider IS NOT NULL AND auth_subject IS NOT NULL "
            "AND btrim(auth_provider) <> '' AND btrim(auth_subject) <> '')",
            name="ck_users_auth_identity_pair",
        ),
        sa.UniqueConstraint(
            "auth_provider",
            "auth_subject",
            name="uq_users_auth_identity",
        ),
        sa.CheckConstraint(
            "email IS NULL OR btrim(email) <> ''",
            name="ck_users_email_not_blank",
        ),
        sa.CheckConstraint(
            "btrim(timezone) <> ''",
            name="ck_users_timezone_not_blank",
        ),
        sa.Index(
            "uq_users_email_normalized",
            sa.text("lower(email)"),
            unique=True,
            postgresql_where=sa.text("email IS NOT NULL"),
            sqlite_where=sa.text("email IS NOT NULL"),
        ),
        sa.Index("ix_users_display_name", "display_name"),
        sa.Index(
            "uq_users_account_id",
            "account_id",
            unique=True,
            postgresql_where=sa.text("account_id IS NOT NULL"),
            sqlite_where=sa.text("account_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True, native_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True, native_uuid=True),
        sa.ForeignKey(
            "accounts.id",
            name="fk_users_account_id_accounts",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    auth_provider: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    auth_subject: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(sa.String(320), nullable=True)
    display_name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        default="UTC",
        server_default=sa.text("'UTC'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    account: Mapped[Account | None] = relationship(back_populates="user")
    memberships: Mapped[list[GroupMembership]] = relationship(
        back_populates="user",
        passive_deletes="all",
    )
    confirmed_sessions: Mapped[list[ConfirmedSession]] = relationship(
        back_populates="confirmed_by_user",
        passive_deletes="all",
    )
    availability_entries: Mapped[list[Availability]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Group(Base):
    __tablename__ = "groups"
    __table_args__ = (
        sa.CheckConstraint(
            "btrim(name) <> ''",
            name="ck_groups_name_not_blank",
        ),
        sa.CheckConstraint(
            "btrim(timezone) <> ''",
            name="ck_groups_timezone_not_blank",
        ),
        sa.Index("ix_groups_name", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True, native_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        default="UTC",
        server_default=sa.text("'UTC'"),
    )
    description: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    memberships: Mapped[list[GroupMembership]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    confirmed_sessions: Mapped[list[ConfirmedSession]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class GroupMembership(Base):
    __tablename__ = "group_memberships"
    __table_args__ = (
        sa.CheckConstraint(
            "role IN ('owner', 'organizer', 'member')",
            name="ck_group_memberships_role",
        ),
        sa.CheckConstraint(
            "display_order >= 0",
            name="ck_group_memberships_display_order",
        ),
        sa.UniqueConstraint(
            "group_id",
            "display_order",
            name="uq_group_memberships_display_order",
        ),
        sa.Index("ix_group_memberships_user_id", "user_id"),
        sa.Index("ix_group_memberships_group_role", "group_id", "role"),
        sa.Index(
            "uq_group_memberships_one_owner",
            "group_id",
            unique=True,
            postgresql_where=sa.text("role = 'owner'"),
            sqlite_where=sa.text("role = 'owner'"),
        ),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True, native_uuid=True),
        sa.ForeignKey(
            "groups.id",
            name="fk_group_memberships_group_id_groups",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True, native_uuid=True),
        sa.ForeignKey(
            "users.id",
            name="fk_group_memberships_user_id_users",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    role: Mapped[MembershipRole] = mapped_column(
        membership_role_type,
        nullable=False,
    )
    display_order: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    group: Mapped[Group] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class Availability(Base):
    __tablename__ = "availability"
    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('available', 'maybe', 'unavailable')",
            name="ck_availability_status",
        ),
        sa.Index("ix_availability_day_user_id", "day", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True, native_uuid=True),
        sa.ForeignKey(
            "users.id",
            name="fk_availability_user_id_users",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    day: Mapped[date] = mapped_column(sa.Date(), primary_key=True)
    status: Mapped[AvailabilityStatus] = mapped_column(
        availability_status_type,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    user: Mapped[User] = relationship(back_populates="availability_entries")


class ConfirmedSession(Base):
    __tablename__ = "confirmed_sessions"
    __table_args__ = (
        sa.UniqueConstraint(
            "group_id",
            "day",
            name="uq_confirmed_sessions_group_id_day",
        ),
        sa.Index("ix_confirmed_sessions_day", "day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True, native_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True, native_uuid=True),
        sa.ForeignKey(
            "groups.id",
            name="fk_confirmed_sessions_group_id_groups",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    day: Mapped[date] = mapped_column(sa.Date(), nullable=False)
    confirmed_by_user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True, native_uuid=True),
        sa.ForeignKey(
            "users.id",
            name="fk_confirmed_sessions_confirmed_by_user_id_users",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    confirmed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    group: Mapped[Group] = relationship(back_populates="confirmed_sessions")
    confirmed_by_user: Mapped[User] = relationship(back_populates="confirmed_sessions")


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        sa.CheckConstraint(
            "email IS NULL OR btrim(email) <> ''",
            name="ck_accounts_email_not_blank",
        ),
        sa.CheckConstraint(
            "display_name IS NULL OR btrim(display_name) <> ''",
            name="ck_accounts_display_name_not_blank",
        ),
        sa.CheckConstraint(
            "username IS NULL OR btrim(username) <> ''",
            name="ck_accounts_username_not_blank",
        ),
        sa.Index(
            "uq_accounts_email_normalized",
            sa.text("lower(email)"),
            unique=True,
            postgresql_where=sa.text("email IS NOT NULL"),
            sqlite_where=sa.text("email IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True, native_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str | None] = mapped_column(sa.String(320), nullable=True)
    username: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    display_name: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    profile_synced_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    identities: Mapped[list[AccountIdentity]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    user: Mapped[User | None] = relationship(
        back_populates="account",
        uselist=False,
    )


class AccountIdentity(Base):
    __tablename__ = "account_identities"
    __table_args__ = (
        sa.CheckConstraint(
            "btrim(provider) <> ''",
            name="ck_account_identities_provider_not_blank",
        ),
        sa.CheckConstraint(
            "btrim(provider_subject) <> ''",
            name="ck_account_identities_provider_subject_not_blank",
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_subject",
            name="uq_account_identities_provider_subject",
        ),
        sa.Index("ix_account_identities_account_id", "account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True, native_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True, native_uuid=True),
        sa.ForeignKey(
            "accounts.id",
            name="fk_account_identities_account_id_accounts",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    provider_subject: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    account: Mapped[Account] = relationship(back_populates="identities")
