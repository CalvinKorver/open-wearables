import json
from collections.abc import AsyncIterator, Mapping
from typing import cast

import httpx
import pytest

from app.agent import managed_client
from app.agent.managed_client import ManagedAgentPermissionRequiredError
from app.storage import db


def _sse(*events: Mapping[str, object]) -> bytes:
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
        with pytest.raises(ManagedAgentPermissionRequiredError, match="tool-1"):
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
    agent = cast(dict[str, object], body["agent"])
    assert "injury" in str(agent.get("system"))


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
            raise managed_client._SessionUnavailableError("terminated")
        return "recovered"

    monkeypatch.setattr(managed_client, "_ensure_session", fake_ensure)
    monkeypatch.setattr(managed_client, "_stream_turn", fake_stream)
    assert await managed_client.run_turn("hello") == "recovered"
    assert ensured == ["session-1", "session-2"]
    assert db.get_managed_session_id() == "session-2"


@pytest.mark.asyncio
async def test_clear_session_archives_chat_but_keeps_memory_pointer_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db.set_managed_session_id("session-1")
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "session-1"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(managed_client.httpx, "AsyncClient", lambda **_kwargs: client)
    await managed_client.clear_session()

    assert db.get_managed_session_id() is None
    assert requests[0].url.path == "/v1/sessions/session-1/archive"


@pytest.mark.asyncio
async def test_forget_helpers_delete_live_memories_and_only_matching_coach_sessions() -> None:
    deleted: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "/memory_stores/" in request.url.path:
            return httpx.Response(200, json={"data": [{"type": "memory", "id": "memory-1"}]})
        if request.method == "GET" and request.url.path == "/v1/sessions":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "session-mine",
                            "metadata": {
                                "source": "open-wearables-coach",
                                "telegram_chat_id": "1234567",
                            },
                        },
                        {
                            "id": "session-other",
                            "metadata": {
                                "source": "open-wearables-coach",
                                "telegram_chat_id": "other",
                            },
                        },
                    ],
                    "next_page": None,
                },
            )
        if request.method == "DELETE":
            deleted.append(request.url.path)
            return httpx.Response(204)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await managed_client._delete_all_memories(client)
        await managed_client._delete_all_coach_sessions(client)

    assert deleted == [
        "/v1/memory_stores/memstore_test/memories/memory-1",
        "/v1/sessions/session-mine",
    ]


@pytest.mark.asyncio
async def test_sse_parser_accepts_multiline_data() -> None:
    class FakeResponse:
        async def aiter_lines(self) -> AsyncIterator[str]:
            for line in ['data: {"type":', 'data: "agent.message"}', ""]:
                yield line

    events = [event async for event in managed_client._sse_events(FakeResponse())]
    assert events == [{"type": "agent.message"}]
