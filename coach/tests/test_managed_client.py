import json
from collections.abc import AsyncIterator

import httpx
import pytest

from app.agent import managed_client
from app.agent.managed_client import ManagedAgentPermissionRequired
from app.storage import db


def _sse(*events: dict[str, object]) -> bytes:
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode()


@pytest.fixture(autouse=True)
def _fresh_session() -> None:
    db.init_db()
    db.clear_managed_session()


@pytest.mark.asyncio
async def test_stream_connects_before_sending_and_returns_authoritative_text() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse(
                    {
                        "type": "agent.message",
                        "id": "event-1",
                        "content": [{"type": "text", "text": "<b>Ready</b>"}],
                    },
                    {"type": "session.status_idle", "id": "event-2", "stop_reason": {"type": "end_turn"}},
                ),
            )
        assert json.loads(request.content)["events"][0]["type"] == "user.message"
        return httpx.Response(200, json={"data": [{"id": "user-event"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reply = await managed_client._stream_turn(
            client,
            "session-1",
            "hello",
            update_id=12,
            message_id=34,
        )

    assert reply == "<b>Ready</b>"
    assert calls == [
        "GET /v1/sessions/session-1/events/stream",
        "POST /v1/sessions/session-1/events",
    ]


@pytest.mark.asyncio
async def test_stream_deduplicates_events() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"data": []})
        message = {
            "type": "agent.message",
            "id": "same-id",
            "content": [{"type": "text", "text": "once"}],
        }
        return httpx.Response(
            200,
            content=_sse(message, message, {"type": "session.status_idle", "stop_reason": {"type": "end_turn"}}),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reply = await managed_client._stream_turn(client, "session-1", "hello", update_id=None, message_id=None)
    assert reply == "once"


@pytest.mark.asyncio
async def test_stream_does_not_auto_approve_permissions() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(
            200,
            content=_sse(
                {
                    "type": "session.status_idle",
                    "stop_reason": {"type": "requires_action", "event_ids": ["tool-1"]},
                }
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ManagedAgentPermissionRequired, match="tool-1"):
            await managed_client._stream_turn(client, "session-1", "hello", update_id=None, message_id=None)


@pytest.mark.asyncio
async def test_ensure_session_reuses_active_session() -> None:
    db.set_managed_session_id("session-existing")
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "session-existing", "status": "idle"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        session_id = await managed_client._ensure_session(client)
    assert session_id == "session-existing"
    assert [request.method for request in requests] == ["GET"]


@pytest.mark.asyncio
async def test_ensure_session_creates_with_memory_and_system_policy() -> None:
    body: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        body.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "session-new", "status": "idle"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        session_id = await managed_client._ensure_session(client)

    assert session_id == "session-new"
    assert db.get_managed_session_id() == "session-new"
    assert body["resources"] == [
        {
            "type": "memory_store",
            "memory_store_id": "memstore_test",
            "access": "read_write",
            "instructions": managed_client.MEMORY_ATTACHMENT_INSTRUCTIONS,
        }
    ]
    agent = body["agent"]
    assert isinstance(agent, dict)
    assert "injury" in str(agent["system"])


@pytest.mark.asyncio
async def test_run_turn_replaces_unavailable_session(monkeypatch: pytest.MonkeyPatch) -> None:
    ensured: list[str] = []
    attempts = 0

    async def fake_ensure(_client: httpx.AsyncClient) -> str:
        session_id = f"session-{len(ensured) + 1}"
        ensured.append(session_id)
        db.set_managed_session_id(session_id)
        return session_id

    async def fake_stream(*args: object, **kwargs: object) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise managed_client._SessionUnavailable("terminated")
        return "recovered"

    monkeypatch.setattr(managed_client, "_ensure_session", fake_ensure)
    monkeypatch.setattr(managed_client, "_stream_turn", fake_stream)
    assert await managed_client.run_turn("hello") == "recovered"
    assert ensured == ["session-1", "session-2"]
    assert db.get_managed_session_id() == "session-2"


@pytest.mark.asyncio
async def test_sse_parser_accepts_multiline_data() -> None:
    class FakeResponse:
        async def aiter_lines(self) -> AsyncIterator[str]:
            for line in ['data: {"type":', 'data: "agent.message"}', ""]:
                yield line

    events = [event async for event in managed_client._sse_events(FakeResponse())]  # type: ignore[arg-type]
    assert events == [{"type": "agent.message"}]
