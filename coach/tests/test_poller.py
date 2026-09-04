import asyncio
from typing import Any

import pytest

from app.channels import poller as telegram_poller
from app.channels.telegram import IncomingMessage
from app.storage import db


@pytest.fixture(autouse=True)
def _fresh_offset():
    db.init_db()
    with db.session() as s:
        s.query(db.TelegramState).delete()
        s.commit()
    return


@pytest.mark.asyncio
async def test_poller_drains_stale_updates_then_handles_one(monkeypatch: pytest.MonkeyPatch) -> None:
    handled: list[IncomingMessage] = []
    get_calls: list[int | None] = []
    stop = asyncio.Event()

    async def fake_ack() -> int:
        return 11

    async def fake_get_updates(offset: int | None, **_kwargs: object) -> list[dict[str, Any]]:
        get_calls.append(offset)
        if offset == 11:
            return [
                {
                    "update_id": 11,
                    "message": {"message_id": 4, "chat": {"id": 1234567}, "text": "hi"},
                }
            ]
        return []

    async def fake_handle(message: IncomingMessage) -> None:
        handled.append(message)
        stop.set()

    monkeypatch.setattr("app.channels.telegram.acknowledge_pending", fake_ack)
    monkeypatch.setattr("app.channels.telegram.get_updates", fake_get_updates)
    monkeypatch.setattr("app.channels.poller.handle_incoming", fake_handle)

    await telegram_poller.run_poller(stop)

    assert db.get_telegram_offset() == 12
    assert handled == [IncomingMessage(update_id=11, message_id=4, chat_id="1234567", text="hi")]
    assert get_calls[0] == 11


@pytest.mark.asyncio
async def test_poller_skips_other_chats_but_advances_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    handled: list[IncomingMessage] = []
    n = {"calls": 0}
    stop = asyncio.Event()

    async def fake_ack() -> int | None:
        return None

    async def fake_get_updates(offset: int | None, **_kwargs: object) -> list[dict[str, Any]]:
        n["calls"] += 1
        if n["calls"] == 1:
            return [{"update_id": 5, "message": {"message_id": 1, "chat": {"id": 999}, "text": "nope"}}]
        stop.set()
        return []

    async def fake_handle(message: IncomingMessage) -> None:
        handled.append(message)

    monkeypatch.setattr("app.channels.telegram.acknowledge_pending", fake_ack)
    monkeypatch.setattr("app.channels.telegram.get_updates", fake_get_updates)
    monkeypatch.setattr("app.channels.poller.handle_incoming", fake_handle)

    await telegram_poller.run_poller(stop)
    assert handled == []
    assert db.get_telegram_offset() == 6
