"""Relay Telegram turns to a persistent Claude Managed Agents session."""

import json
from logging import getLogger
from typing import Any, AsyncIterator, Protocol

import httpx

from app.agent.prompts import MANAGED_SYSTEM_PROMPT, MEMORY_ATTACHMENT_INSTRUCTIONS, turn_context
from app.config import settings
from app.storage import db

logger = getLogger(__name__)

_ANTHROPIC_VERSION = "2023-06-01"
_MANAGED_AGENTS_BETA = "managed-agents-2026-04-01"
_MEMORY_BETA = "agent-memory-2026-07-22"


class ManagedAgentError(RuntimeError):
    """Base error for Managed Agents relay failures."""


class ManagedAgentPermissionRequiredError(ManagedAgentError):
    """Raised instead of silently approving a tool permission request."""


class _SessionUnavailableError(ManagedAgentError):
    """The saved session cannot accept another turn."""


class _LineStream(Protocol):
    def aiter_lines(self) -> AsyncIterator[str]: ...


def _headers() -> dict[str, str]:
    return {
        "x-api-key": settings.anthropic_api_key.get_secret_value(),
        "anthropic-version": _ANTHROPIC_VERSION,
        "anthropic-beta": _MANAGED_AGENTS_BETA,
        "content-type": "application/json",
    }


def _memory_headers() -> dict[str, str]:
    headers = _headers()
    headers["anthropic-beta"] = _MEMORY_BETA
    return headers


def _url(path: str) -> str:
    return f"{settings.anthropic_api_url.rstrip('/')}{path}"


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:1000]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(body)


def _raise_for_status(response: httpx.Response, action: str) -> None:
    if response.is_success:
        return
    detail = _error_detail(response)
    if response.status_code in {404, 409, 410}:
        raise _SessionUnavailableError(f"{action} failed ({response.status_code}): {detail}")
    raise ManagedAgentError(f"{action} failed ({response.status_code}): {detail}")


def _session_payload() -> dict[str, Any]:
    return {
        "agent": {
            "type": "agent_with_overrides",
            "id": settings.managed_agent_id,
            "system": MANAGED_SYSTEM_PROMPT,
        },
        "environment_id": settings.managed_environment_id,
        "vault_ids": settings.vault_ids,
        "resources": [
            {
                "type": "memory_store",
                "memory_store_id": settings.managed_memory_store_id,
                "access": "read_write",
                "instructions": MEMORY_ATTACHMENT_INSTRUCTIONS,
            }
        ],
        "metadata": {
            "source": "open-wearables-coach",
            "telegram_chat_id": settings.telegram_chat_id,
            "open_wearables_user_id": settings.ow_user_id,
        },
        "title": f"Open Wearables Telegram coach ({settings.telegram_chat_id})",
    }


async def _create_session(client: httpx.AsyncClient) -> str:
    response = await client.post(_url("/v1/sessions"), headers=_headers(), json=_session_payload())
    _raise_for_status(response, "Create managed session")
    payload = response.json()
    session_id = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(session_id, str) or not session_id:
        raise ManagedAgentError("Create managed session returned no session ID")
    db.set_managed_session_id(session_id)
    logger.info("Created managed session id=%s", session_id)
    return session_id


async def _ensure_session(client: httpx.AsyncClient) -> str:
    session_id = db.get_managed_session_id()
    if session_id is None:
        return await _create_session(client)

    response = await client.get(_url(f"/v1/sessions/{session_id}"), headers=_headers())
    if response.status_code == 404:
        db.clear_managed_session()
        return await _create_session(client)
    _raise_for_status(response, "Retrieve managed session")
    payload = response.json()
    if isinstance(payload, dict) and payload.get("status") == "terminated":
        db.clear_managed_session()
        return await _create_session(client)
    return session_id


def _turn_event(text: str, *, update_id: int | None, message_id: int | None) -> dict[str, Any]:
    context = turn_context(update_id=update_id, message_id=message_id)
    return {
        "type": "user.message",
        "content": [
            {"type": "text", "text": text},
            {"type": "text", "text": f"<trusted_turn_context>\n{context}\n</trusted_turn_context>"},
        ],
    }


async def _send_turn(
    client: httpx.AsyncClient,
    session_id: str,
    text: str,
    *,
    update_id: int | None,
    message_id: int | None,
) -> None:
    response = await client.post(
        _url(f"/v1/sessions/{session_id}/events"),
        headers=_headers(),
        json={"events": [_turn_event(text, update_id=update_id, message_id=message_id)]},
    )
    _raise_for_status(response, "Send managed session event")


async def _sse_events(response: _LineStream) -> AsyncIterator[dict[str, Any]]:
    """Yield JSON objects from SSE ``data:`` records."""
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if data_lines:
                raw = "\n".join(data_lines)
                data_lines.clear()
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ManagedAgentError("Managed Agents stream returned invalid JSON") from exc
                if isinstance(event, dict):
                    yield event
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        try:
            event = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise ManagedAgentError("Managed Agents stream returned invalid JSON") from exc
        if isinstance(event, dict):
            yield event


def _message_text(event: dict[str, Any]) -> str:
    content = event.get("content")
    if not isinstance(content, list):
        return ""
    parts = [
        block["text"]
        for block in content
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
    ]
    return "".join(parts).strip()


def _stream_error(event: dict[str, Any]) -> str:
    error = event.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error or "unknown managed-agent error")


async def _stream_turn(
    client: httpx.AsyncClient,
    session_id: str,
    text: str,
    *,
    update_id: int | None,
    message_id: int | None,
) -> str:
    stream_url = _url(f"/v1/sessions/{session_id}/events/stream")
    async with client.stream("GET", stream_url, headers={**_headers(), "accept": "text/event-stream"}) as response:
        _raise_for_status(response, "Open managed session stream")
        # Entering the stream context waits for response headers, so no turn can
        # complete before the listener is connected.
        await _send_turn(
            client,
            session_id,
            text,
            update_id=update_id,
            message_id=message_id,
        )

        messages: list[str] = []
        seen_ids: set[str] = set()
        async for event in _sse_events(response):
            event_type = event.get("type")
            event_id = event.get("id")
            if isinstance(event_id, str):
                if event_id in seen_ids:
                    continue
                seen_ids.add(event_id)

            if event_type == "agent.message":
                message = _message_text(event)
                if message:
                    messages.append(message)
            elif event_type == "session.error":
                raise ManagedAgentError(_stream_error(event))
            elif event_type == "session.status_terminated":
                raise _SessionUnavailableError("Managed session terminated while processing the turn")
            elif event_type == "session.status_idle":
                reason = event.get("stop_reason")
                reason_type = reason.get("type") if isinstance(reason, dict) else None
                if reason_type == "requires_action":
                    event_ids = reason.get("event_ids", []) if isinstance(reason, dict) else []
                    raise ManagedAgentPermissionRequiredError(
                        "Managed Agent requested tool approval. Configure only the coach's read-only MCP tools "
                        f"with always_allow; pending event IDs: {event_ids}"
                    )
                if reason_type != "end_turn":
                    raise ManagedAgentError(
                        f"Managed Agent stopped before completing the turn: {reason_type or 'unknown'}"
                    )
                break

    reply = "\n".join(messages).strip()
    if not reply:
        raise ManagedAgentError("Managed Agent completed the turn without a text reply")
    return reply


async def run_turn(
    text: str,
    *,
    update_id: int | None = None,
    message_id: int | None = None,
) -> str:
    """Send one turn and return the authoritative agent response text."""
    timeout = httpx.Timeout(settings.managed_agent_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(2):
            session_id = await _ensure_session(client)
            try:
                return await _stream_turn(
                    client,
                    session_id,
                    text,
                    update_id=update_id,
                    message_id=message_id,
                )
            except _SessionUnavailableError:
                db.clear_managed_session()
                if attempt:
                    raise
                logger.warning("Managed session %s unavailable; creating a replacement", session_id)
    raise ManagedAgentError("Managed Agent turn failed")


async def clear_session() -> None:
    """Archive the active session and clear its local pointer.

    The attached memory store is independent and remains available to the next
    session. Archiving keeps the previous chat inspectable in Anthropic.
    """
    session_id = db.get_managed_session_id()
    if session_id is None:
        return
    timeout = httpx.Timeout(settings.managed_agent_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(_url(f"/v1/sessions/{session_id}/archive"), headers=_headers())
        if response.status_code != 404:
            _raise_for_status(response, "Archive managed session")
    db.clear_managed_session()
    logger.info("Archived managed session id=%s", session_id)


async def forget_all_data() -> None:
    """Delete live durable memories and all coach sessions for this chat.

    Anthropic may retain immutable memory versions for its documented retention
    window. Deleting the memory store itself would invalidate the configured
    store ID, so this clears every live memory while preserving the empty store.
    """
    timeout = httpx.Timeout(settings.managed_agent_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        await _delete_all_memories(client)
        await _delete_all_coach_sessions(client)
    db.clear_managed_session()


async def _delete_all_memories(client: httpx.AsyncClient) -> None:
    store_id = settings.managed_memory_store_id
    response = await client.get(
        _url(f"/v1/memory_stores/{store_id}/memories"),
        headers=_memory_headers(),
        params={"path_prefix": "/", "depth": 0},
    )
    _raise_for_status(response, "List managed memories")
    payload = response.json()
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    for row in rows:
        memory_id = row.get("id") if isinstance(row, dict) else None
        if not isinstance(memory_id, str):
            continue
        delete_response = await client.delete(
            _url(f"/v1/memory_stores/{store_id}/memories/{memory_id}"),
            headers=_memory_headers(),
        )
        _raise_for_status(delete_response, f"Delete managed memory {memory_id}")


async def _delete_all_coach_sessions(client: httpx.AsyncClient) -> None:
    page: str | None = None
    session_ids: list[str] = []
    while True:
        params: dict[str, Any] = {
            "agent_id": settings.managed_agent_id,
            "memory_store_id": settings.managed_memory_store_id,
            "include_archived": "true",
            "limit": 100,
        }
        if page:
            params["page"] = page
        response = await client.get(_url("/v1/sessions"), headers=_headers(), params=params)
        _raise_for_status(response, "List managed sessions")
        payload = response.json()
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            metadata = row.get("metadata")
            if not isinstance(metadata, dict) or metadata.get("source") != "open-wearables-coach":
                continue
            if str(metadata.get("telegram_chat_id")) != str(settings.telegram_chat_id):
                continue
            session_id = row.get("id")
            if isinstance(session_id, str):
                session_ids.append(session_id)
        page = payload.get("next_page") if isinstance(payload, dict) else None
        if not isinstance(page, str) or not page:
            break
    for session_id in session_ids:
        delete_response = await client.delete(_url(f"/v1/sessions/{session_id}"), headers=_headers())
        if delete_response.status_code != 404:
            _raise_for_status(delete_response, f"Delete managed session {session_id}")
