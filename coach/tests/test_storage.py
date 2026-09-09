from datetime import date

import pytest

from app.storage import db
from app.storage.db import BriefingStatus, MemoryFullError, MemoryKind, MemoryTooLongError


@pytest.fixture(autouse=True)
def _fresh_db():
    db.init_db()
    with db.session() as s:
        s.query(db.BriefingRun).delete()
        s.query(db.ConversationTurn).delete()
        s.query(db.TelegramState).delete()
        s.query(db.MemoryItem).delete()
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


def test_conversation_turns_are_chronological_and_pruned():
    for i in range(db.MAX_CONVERSATION_TURNS + 3):
        db.append_conversation_turn("user" if i % 2 == 0 else "assistant", f"turn-{i}")

    turns = db.get_conversation_turns()
    assert len(turns) == db.MAX_CONVERSATION_TURNS
    assert turns[0][1] == "turn-3"
    assert turns[-1][1] == f"turn-{db.MAX_CONVERSATION_TURNS + 2}"


def test_clear_conversation_deletes_all_turns():
    db.append_conversation_turn("user", "hi")
    db.append_conversation_turn("assistant", "hello")
    db.clear_conversation()
    assert db.get_conversation_turns() == []


def test_add_and_list_memory():
    goal = db.add_memory(MemoryKind.GOAL, "Race 70.3 in October")
    fact = db.add_memory(MemoryKind.FACT, "Prefer morning workouts")
    assert goal.id is not None
    assert fact.kind == MemoryKind.FACT
    assert [i.content for i in db.list_memory(MemoryKind.GOAL)] == ["Race 70.3 in October"]
    assert [i.content for i in db.list_memory(MemoryKind.FACT)] == ["Prefer morning workouts"]
    assert len(db.list_memory()) == 2


def test_add_memory_rejects_empty_and_too_long():
    with pytest.raises(ValueError, match="must not be empty"):
        db.add_memory(MemoryKind.GOAL, "   ")
    with pytest.raises(MemoryTooLongError):
        db.add_memory(MemoryKind.FACT, "x" * (db.MAX_MEMORY_CONTENT_CHARS + 1))


def test_add_memory_enforces_caps():
    for i in range(db.MAX_GOALS):
        db.add_memory(MemoryKind.GOAL, f"goal-{i}")
    with pytest.raises(MemoryFullError):
        db.add_memory(MemoryKind.GOAL, "one too many")


def test_delete_and_clear_memory():
    g = db.add_memory(MemoryKind.GOAL, "A")
    db.add_memory(MemoryKind.FACT, "B")
    assert db.delete_memory(g.id) is True
    assert db.delete_memory(g.id) is False
    assert db.clear_memory(MemoryKind.FACT) == 1
    assert db.list_memory() == []


def test_clear_conversation_does_not_wipe_memory():
    db.add_memory(MemoryKind.GOAL, "Keep me")
    db.append_conversation_turn("user", "hi")
    db.clear_conversation()
    assert db.get_conversation_turns() == []
    assert [i.content for i in db.list_memory()] == ["Keep me"]


def test_format_memory_block_empty_and_populated():
    assert db.format_memory_block() == ""
    db.add_memory(MemoryKind.GOAL, "Race soon")
    db.add_memory(MemoryKind.FACT, "No evenings")
    block = db.format_memory_block()
    assert "Durable profile" in block
    assert "Race soon" in block
    assert "No evenings" in block
