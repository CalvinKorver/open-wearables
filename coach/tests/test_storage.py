from datetime import date

import pytest

from app.storage import db
from app.storage.db import BriefingStatus


@pytest.fixture(autouse=True)
def _fresh_db():
    db.init_db()
    with db.session() as s:
        s.query(db.BriefingRun).delete()
        s.query(db.ManagedSessionState).delete()
        s.query(db.TelegramState).delete()
        s.commit()
    return


def test_claim_run_creates_row_when_none_exists():
    d = date(2026, 5, 7)
    row = db.claim_run(d)
    assert row is not None
    assert row.local_date == d
    assert row.status == BriefingStatus.PENDING


def test_claim_run_returns_none_when_already_sent():
    d = date(2026, 5, 7)
    db.claim_run(d)
    db.mark_sent(d, message_id="42")

    again = db.claim_run(d)
    assert again is None


def test_claim_run_with_force_reruns_even_after_sent():
    d = date(2026, 5, 7)
    db.claim_run(d)
    db.mark_sent(d, message_id="42")

    again = db.claim_run(d, force=True)
    assert again is not None
    assert again.status == BriefingStatus.PENDING


def test_claim_run_reclaims_failed_row():
    d = date(2026, 5, 7)
    db.claim_run(d)
    db.mark_failed(d, error="boom")

    again = db.claim_run(d)
    assert again is not None
    assert again.status == BriefingStatus.PENDING


def test_mark_sent_records_message_id():
    d = date(2026, 5, 7)
    db.claim_run(d)
    db.mark_sent(d, message_id="abc")

    row = db.get_run(d)
    assert row is not None
    assert row.status == BriefingStatus.SENT
    assert row.message_id == "abc"
    assert row.sent_at is not None


def test_mark_failed_truncates_long_error():
    d = date(2026, 5, 7)
    db.claim_run(d)
    db.mark_failed(d, error="x" * 5000)

    row = db.get_run(d)
    assert row is not None
    assert row.status == BriefingStatus.FAILED
    assert row.error is not None
    assert len(row.error) <= 2048


def test_telegram_offset_round_trip():
    assert db.get_telegram_offset() is None
    db.set_telegram_offset(42)
    assert db.get_telegram_offset() == 42
    db.set_telegram_offset(43)
    assert db.get_telegram_offset() == 43


def test_managed_session_round_trip_and_clear():
    assert db.get_managed_session_id() is None
    db.set_managed_session_id("session-1")
    assert db.get_managed_session_id() == "session-1"
    db.set_managed_session_id("session-2")
    assert db.get_managed_session_id() == "session-2"
    db.clear_managed_session()
    assert db.get_managed_session_id() is None


def test_init_db_removes_legacy_local_conversation_table():
    with db._engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS conversation_turn "
            "(id INTEGER PRIMARY KEY, role VARCHAR(16), content TEXT, created_at DATETIME)"
        )
    db.init_db()
    with db._engine.connect() as connection:
        names = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='conversation_turn'"
        ).all()
    assert names == []
