from datetime import date

import pytest

from app.storage import db
from app.storage.db import BriefingStatus


@pytest.fixture(autouse=True)
def _fresh_db():
    db.init_db()
    with db.session() as s:
        s.query(db.BriefingRun).delete()
        s.commit()
    yield


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
