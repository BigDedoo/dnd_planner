import pytest

from backend.tests.test_session_reminders import ReminderCases


@pytest.fixture
def lifecycle_engine(postgres_engine, db_session):
    return postgres_engine


class TestPostgresReminders(ReminderCases):
    pass
