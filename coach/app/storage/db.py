"""SQLite storage for the coach service.

Persisted state:
- ``briefing_run`` — one row per local date, an idempotency guard so a date is
  never briefed twice unless ``--force``.
- ``telegram_state`` — getUpdates offset so restarts do not re-handle old DMs.
- ``managed_session_state`` — the active Anthropic Managed Agents session ID.

Conversation and semantic memory live only in Anthropic Managed Agents.
"""

from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import Path

from sqlalchemy import Date, DateTime, Integer, String, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import settings


class BriefingStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class Base(DeclarativeBase):
    pass


class BriefingRun(Base):
    __tablename__ = "briefing_run"

    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(String(2048), nullable=True)


class TelegramState(Base):
    """Singleton row (id=1) holding the next getUpdates offset."""

    __tablename__ = "telegram_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    next_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ManagedSessionState(Base):
    """Singleton row (id=1) for the active Anthropic session."""

    __tablename__ = "managed_session_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


def _build_engine_url(db_path: str) -> str:
    p = Path(db_path)
    if not p.is_absolute():
        p = Path.cwd() / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{p}"


_engine = create_engine(_build_engine_url(settings.coach_db_path), echo=False, future=True)
_SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def init_db() -> None:
    """Create tables if they don't yet exist. Safe to call repeatedly."""
    Base.metadata.create_all(_engine)
    # Conversation history moved to Anthropic sessions. Remove legacy local copies.
    with _engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS conversation_turn"))


def session() -> Session:
    """Return a new SQLAlchemy session bound to the coach database."""
    return _SessionLocal()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def claim_run(local_date: date, *, force: bool = False) -> BriefingRun | None:
    """Reserve a briefing slot for the given local date.

    Returns the BriefingRun row on success. Returns None if a row already
    exists with status SENT (and force is False), meaning the briefing has
    already been delivered and should not run again.

    A row in PENDING or FAILED state is taken over (re-claimed) so that a
    crashed or previously-failed run can be retried.
    """
    with session() as s:
        existing = s.get(BriefingRun, local_date)
        now = utcnow()
        if existing is not None:
            if existing.status == BriefingStatus.SENT and not force:
                return None
            existing.status = BriefingStatus.PENDING
            existing.started_at = now
            existing.sent_at = None
            existing.message_id = None
            existing.error = None
            s.commit()
            s.refresh(existing)
            return existing
        row = BriefingRun(
            local_date=local_date,
            status=BriefingStatus.PENDING,
            started_at=now,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def mark_sent(local_date: date, message_id: str | None) -> None:
    with session() as s:
        row = s.get(BriefingRun, local_date)
        if row is None:
            return
        row.status = BriefingStatus.SENT
        row.sent_at = utcnow()
        row.message_id = message_id
        row.error = None
        s.commit()


def mark_failed(local_date: date, error: str) -> None:
    with session() as s:
        row = s.get(BriefingRun, local_date)
        if row is None:
            return
        row.status = BriefingStatus.FAILED
        row.error = error[:2048]
        s.commit()


def get_run(local_date: date) -> BriefingRun | None:
    with session() as s:
        return s.get(BriefingRun, local_date)


def get_telegram_offset() -> int | None:
    with session() as s:
        row = s.get(TelegramState, 1)
        return row.next_offset if row is not None else None


def set_telegram_offset(offset: int) -> None:
    with session() as s:
        row = s.get(TelegramState, 1)
        if row is None:
            s.add(TelegramState(id=1, next_offset=offset))
        else:
            row.next_offset = offset
        s.commit()


def get_managed_session_id() -> str | None:
    with session() as s:
        row = s.get(ManagedSessionState, 1)
        return row.session_id if row is not None else None


def set_managed_session_id(session_id: str) -> None:
    with session() as s:
        row = s.get(ManagedSessionState, 1)
        if row is None:
            s.add(ManagedSessionState(id=1, session_id=session_id, created_at=utcnow()))
        else:
            row.session_id = session_id
            row.created_at = utcnow()
        s.commit()


def clear_managed_session() -> None:
    with session() as s:
        row = s.get(ManagedSessionState, 1)
        if row is not None:
            s.delete(row)
        s.commit()
