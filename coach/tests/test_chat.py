from contextlib import asynccontextmanager
from datetime import date
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.channels.telegram import IncomingMessage
from app.chat import HELP_TEXT, handle_incoming, normalize_command
from app.storage import db


@pytest.fixture(autouse=True)
def _fresh_conversation():
    db.init_db()
    with db.session() as s:
        s.query(db.ConversationTurn).delete()
        s.commit()
    return


def test_normalize_command_strips_bot_suffix():
    assert normalize_command("/help@ow_coach_bot") == "/help"
    assert normalize_command("/brief@ow_coach_bot please") == "/brief please"
    assert normalize_command("How did I sleep?") == "How did I sleep?"


@pytest.mark.asyncio
async def test_handle_incoming_help(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, int | None]] = []

    async def fake_reply(text: str, *, reply_to_message_id: int | None = None) -> str:
        sent.append((text, reply_to_message_id))
        return "1"

    monkeypatch.setattr("app.chat.send_reply", fake_reply)
    await handle_incoming(IncomingMessage(1, 9, "1234567", "/help@ow_coach_bot"))
    assert sent == [(HELP_TEXT, 9)]


@pytest.mark.asyncio
async def test_handle_incoming_non_text_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    async def fake_reply(text: str, *, reply_to_message_id: int | None = None) -> str:
        sent.append(text)
        return "1"

    monkeypatch.setattr("app.chat.send_reply", fake_reply)
    await handle_incoming(IncomingMessage(1, 9, "1234567", ""))
    assert sent and "only read text" in sent[0]


@pytest.mark.asyncio
async def test_handle_incoming_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    db.append_conversation_turn("user", "hi")
    sent: list[str] = []

    async def fake_reply(text: str, *, reply_to_message_id: int | None = None) -> str:
        sent.append(text)
        return "1"

    monkeypatch.setattr("app.chat.send_reply", fake_reply)
    await handle_incoming(IncomingMessage(1, 9, "1234567", "/clear"))
    assert db.get_conversation_turns() == []
    assert sent and "Cleared" in sent[0]


@pytest.mark.asyncio
async def test_handle_incoming_brief_forces_yesterday(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Any] = {}

    async def fake_run(local_date: date, *, force: bool = False) -> None:
        called["date"] = local_date
        called["force"] = force

    monkeypatch.setattr("app.chat.run_for_date", fake_run)
    monkeypatch.setattr("app.chat.yesterday_local", lambda: date(2026, 5, 7))
    await handle_incoming(IncomingMessage(1, 9, "1234567", "/brief"))
    assert called == {"date": date(2026, 5, 7), "force": True}


@pytest.mark.asyncio
async def test_handle_incoming_question_saves_turns_and_replies(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, int | None]] = []

    async def fake_reply(text: str, *, reply_to_message_id: int | None = None) -> str:
        sent.append((text, reply_to_message_id))
        return "1"

    @asynccontextmanager
    async def fake_mcp():
        yield object()

    async def fake_generate(session: object, user_text: str, history: list[tuple[str, str]]) -> str:
        assert user_text == "How did I sleep?"
        assert history == []
        return "<b>7h 12m</b> last night."

    monkeypatch.setattr("app.chat.send_reply", fake_reply)
    monkeypatch.setattr("app.chat.send_chat_action", AsyncMock())
    monkeypatch.setattr("app.chat.open_mcp_client", fake_mcp)
    monkeypatch.setattr("app.chat.generate_reply", fake_generate)

    await handle_incoming(IncomingMessage(1, 9, "1234567", "How did I sleep?"))

    assert sent == [("<b>7h 12m</b> last night.", 9)]
    assert db.get_conversation_turns() == [
        ("user", "How did I sleep?"),
        ("assistant", "<b>7h 12m</b> last night."),
    ]


@pytest.mark.asyncio
async def test_handle_incoming_question_alerts_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    alerts: list[str] = []

    @asynccontextmanager
    async def fake_mcp():
        yield object()

    async def boom(*args: object, **kwargs: object) -> str:
        raise RuntimeError("mcp down")

    async def fake_alert(text: str) -> str:
        alerts.append(text)
        return "1"

    monkeypatch.setattr("app.chat.send_chat_action", AsyncMock())
    monkeypatch.setattr("app.chat.open_mcp_client", fake_mcp)
    monkeypatch.setattr("app.chat.generate_reply", boom)
    monkeypatch.setattr("app.chat.send_alert", fake_alert)

    await handle_incoming(IncomingMessage(1, 9, "1234567", "sleep?"))
    assert alerts and "mcp down" in alerts[0]
    assert db.get_conversation_turns() == []
