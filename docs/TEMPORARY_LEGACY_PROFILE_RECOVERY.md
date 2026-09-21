# Self-service legacy profile recovery is retired

**SELF-SERVICE LEGACY PROFILE RECOVERY HAS BEEN RETIRED.**

New authenticated users now use the normal onboarding flow and create a new
DnD Planner profile. The application no longer lists historical profiles,
shows their group memberships, or lets a user claim one.

This retirement is intentional. The former public recovery mechanism could not
prove that an authenticated account owned the historical profile it selected.

Unclaimed historical profiles and their related application data have not been
deleted. The `legacy_profile_recoveries` table and its SQLAlchemy model also
remain temporarily so the existing database schema continues to match Alembic
revision `0010_legacy_profile_recoveries` without a migration.

A later, separate schema-cleanup migration may remove the unused table and
model after their historical retention requirements have been reviewed. This
retirement does not provide an operator recovery procedure.
