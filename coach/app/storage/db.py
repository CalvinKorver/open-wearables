"""SQLite storage for the coach service.

Persisted state:
- ``briefing_run`` — one row per local date, an idempotency guard so a date is
  never briefed twice unless ``--force``.
- ``telegram_state`` — getUpdates offset so restarts do not re-handle old DMs.
- ``conversation_turn`` — recent Telegram chat history for multi-turn replies.
- ``memory_item`` — durable goals and facts (survive ``/clear`` and restarts).
"""

from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import Path

from sqlalchemy import Date, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import settings

MAX_CONVERSATION_TURNS = 20
MAX_TURN_CHARS = 8000
MAX_MEMORY_CONTENT_CHARS = 500
MAX_GOALS = 20
MAX_FACTS = 40


class BriefingStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class MemoryKind(StrEnum):
    GOAL = "goal"
    FACT = "fact"


class MemoryFullError(ValueError):
    """Raised when the per-kind durable memory cap is reached."""


class MemoryTooLongError(ValueError):
    """Raised when durable memory content exceeds the character cap."""


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


class ConversationTurn(Base):
    __tablename__ = "conversation_turn"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class MemoryItem(Base):
    __tablename__ = "memory_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


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


def get_conversation_turns(limit: int = MAX_CONVERSATION_TURNS) -> list[tuple[str, str]]:
    """Return recent (role, content) turns in chronological order."""
    with session() as s:
        rows = s.query(ConversationTurn).order_by(ConversationTurn.id.desc()).limit(limit).all()
        rows.reverse()
        return [(row.role, row.content) for row in rows]


def append_conversation_turn(role: str, content: str) -> None:
    with session() as s:
        s.add(
            ConversationTurn(
                role=role,
                content=content[:MAX_TURN_CHARS],
                created_at=utcnow(),
            )
        )
        s.commit()
        ids = [row.id for row in s.query(ConversationTurn.id).order_by(ConversationTurn.id.desc()).all()]
        extra = ids[MAX_CONVERSATION_TURNS:]
        if extra:
            s.query(ConversationTurn).filter(ConversationTurn.id.in_(extra)).delete(synchronize_session=False)
            s.commit()


def clear_conversation() -> None:
    with session() as s:
        s.query(ConversationTurn).delete()
        s.commit()


def _memory_cap(kind: MemoryKind) -> int:
    return MAX_GOALS if kind == MemoryKind.GOAL else MAX_FACTS


def list_memory(kind: MemoryKind | None = None) -> list[MemoryItem]:
    """Return durable memory items in chronological order."""
    with session() as s:
        q = s.query(MemoryItem).order_by(MemoryItem.id.asc())
        if kind is not None:
            q = q.filter(MemoryItem.kind == kind.value)
        rows = q.all()
        # Detach for use outside the session.
        return [
            MemoryItem(
                id=row.id,
                kind=row.kind,
                content=row.content,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]


def add_memory(kind: MemoryKind, content: str) -> MemoryItem:
    """Insert a durable goal or fact. Raises ValueError subclasses on validation failure."""
    text = content.strip()
    if not text:
        raise ValueError("Memory content must not be empty")
    if len(text) > MAX_MEMORY_CONTENT_CHARS:
        raise MemoryTooLongError(f"Memory text must be at most {MAX_MEMORY_CONTENT_CHARS} characters (got {len(text)})")
    with session() as s:
        count = s.query(MemoryItem).filter(MemoryItem.kind == kind.value).count()
        cap = _memory_cap(kind)
        if count >= cap:
            raise MemoryFullError(
                f"At most {cap} {kind.value}s can be saved (currently {count}). Forget one with /forget <id> first."
            )
        now = utcnow()
        row = MemoryItem(kind=kind.value, content=text, created_at=now, updated_at=now)
        s.add(row)
        s.commit()
        s.refresh(row)
        return MemoryItem(
            id=row.id,
            kind=row.kind,
            content=row.content,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


def delete_memory(item_id: int) -> bool:
    """Delete one memory item by id. Returns False if it did not exist."""
    with session() as s:
        row = s.get(MemoryItem, item_id)
        if row is None:
            return False
        s.delete(row)
        s.commit()
        return True


def clear_memory(kind: MemoryKind | None = None) -> int:
    """Delete durable memory items. Returns the number of rows removed."""
    with session() as s:
        q = s.query(MemoryItem)
        if kind is not None:
            q = q.filter(MemoryItem.kind == kind.value)
        count = q.count()
        q.delete(synchronize_session=False)
        s.commit()
        return count


def format_memory_block() -> str:
    """Prompt-ready durable profile, or empty string when nothing is stored."""
    goals = list_memory(MemoryKind.GOAL)
    facts = list_memory(MemoryKind.FACT)
    if not goals and not facts:
        return ""
    lines = [
        "Durable profile (user-set; treat as ground truth unless they update it):",
    ]
    if goals:
        lines.append("Goals:")
        for item in goals:
            lines.append(f"- (#{item.id}) {item.content}")
    if facts:
        lines.append("Facts:")
        for item in facts:
            lines.append(f"- (#{item.id}) {item.content}")
    return "\n".join(lines)
