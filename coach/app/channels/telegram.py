"""Telegram channel: outbound sends and inbound long-polling.

We send with parse_mode=HTML rather than MarkdownV2. HTML only requires escaping
three characters (<, >, &) so the model produces correct markup far more
reliably than MarkdownV2, where every literal `.` or `!` would need a backslash.

If the HTML send is still rejected for any reason (e.g. the model emitted an
unbalanced tag), we fall back to a plain-text send with no parse_mode so the
message always reaches the user.

Outbound paths:
- send_briefing: the daily message; expects HTML already produced by the model.
- send_reply: an inbound-chat answer; HTML with the same fallback, split at 4096.
- send_alert: a plain-text fatal-error notice.

Inbound path: getUpdates long-polling (no public webhook URL required).
"""

import html
from dataclasses import dataclass
from logging import getLogger
from typing import Any

import httpx

from app.config import settings

logger = getLogger(__name__)


_TELEGRAM_API_BASE = "https://api.telegram.org"
_TELEGRAM_MAX_LEN = 4096

_TELEGRAM_BAD_REQUEST = 400
_TELEGRAM_UNAUTHORIZED = 401

_POLL_TIMEOUT_SECONDS = 25


@dataclass(frozen=True)
class IncomingMessage:
    """A text (or empty non-text) message from the configured Telegram chat."""

    update_id: int
    message_id: int
    chat_id: str
    text: str


class _TelegramBadRequestError(Exception):
    """Raised when Telegram returns a 400 (e.g. parse_mode formatting issue)."""

    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.description = description


class TelegramAPIError(Exception):
    """Raised when Telegram returns a non-400 failure."""


def escape_html(text: str) -> str:
    """Escape <, >, and & for Telegram HTML mode."""
    return html.escape(text, quote=False)


def _strip_tags(text: str) -> str:
    """Remove the HTML tags Telegram allows so we can downgrade to plain text."""
    out: list[str] = []
    in_tag = False
    for ch in text:
        if ch == "<":
            in_tag = True
            continue
        if ch == ">" and in_tag:
            in_tag = False
            continue
        if not in_tag:
            out.append(ch)
    return html.unescape("".join(out))


def _truncate(text: str, limit: int = _TELEGRAM_MAX_LEN) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "\u2026"


def _split_message(text: str, limit: int = _TELEGRAM_MAX_LEN) -> list[str]:
    """Split a message into Telegram-sized chunks, preferring newline then space."""
    remaining = text.strip()
    if not remaining:
        return [""]
    chunks: list[str] = []
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        window = remaining[:limit]
        split_at = window.rfind("\n")
        if split_at < limit // 4:
            split_at = window.rfind(" ")
        if split_at < limit // 4:
            split_at = limit
        chunk = remaining[:split_at].rstrip()
        if not chunk:
            chunk = remaining[:limit]
            remaining = remaining[limit:]
        else:
            remaining = remaining[len(chunk) :].lstrip()
        chunks.append(chunk)
    return chunks


def _api_url(method: str) -> str:
    token = settings.telegram_bot_token.get_secret_value()
    return f"{_TELEGRAM_API_BASE}/bot{token}/{method}"


def _require_ok(response: httpx.Response, method: str) -> dict[str, Any]:
    if response.status_code == _TELEGRAM_BAD_REQUEST:
        try:
            description = response.json().get("description", response.text)
        except ValueError:
            description = response.text
        logger.error("Telegram %s 400: %s", method, description)
        raise _TelegramBadRequestError(str(description))

    if response.status_code == _TELEGRAM_UNAUTHORIZED:
        raise TelegramAPIError(f"Telegram {method} unauthorized — check TELEGRAM_BOT_TOKEN")

    if response.status_code != 200:
        logger.error("Telegram %s failed: status=%s body=%s", method, response.status_code, response.text)
        raise TelegramAPIError(f"Telegram {method} failed: status={response.status_code}")

    try:
        data = response.json()
    except ValueError as e:
        raise TelegramAPIError(f"Telegram {method} returned non-JSON") from e

    if not data.get("ok"):
        logger.error("Telegram %s returned ok=false: %s", method, data)
        raise TelegramAPIError(f"Telegram {method} error: {data.get('description')}")
    return data


async def verify_bot() -> dict[str, Any]:
    """Call getMe so a bad token fails at startup instead of on the first send."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(_api_url("getMe"))
    data = _require_ok(response, "getMe")
    result = data.get("result") or {}
    if not isinstance(result, dict):
        result = {}
    logger.info(
        "Telegram bot connected username=%s id=%s",
        result.get("username"),
        result.get("id"),
    )
    return result


async def send_chat_action(action: str = "typing") -> None:
    """Best-effort typing indicator. Telegram shows it for a few seconds."""
    payload = {"chat_id": settings.telegram_chat_id, "action": action}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(_api_url("sendChatAction"), json=payload)
    _require_ok(response, "sendChatAction")


async def send_briefing(text: str) -> str | None:
    """Send the daily briefing as HTML; fall back to plain text if HTML is rejected."""
    try:
        return await _send(text, parse_mode="HTML")
    except _TelegramBadRequestError as e:
        logger.warning("Telegram rejected HTML briefing (%s); retrying as plain text", e.description)
        return await _send(_strip_tags(text), parse_mode=None)


async def send_reply(text: str, *, reply_to_message_id: int | None = None) -> str | None:
    """Send a chat reply as HTML (split if needed); fall back to plain text per chunk."""
    last_id: str | None = None
    for index, chunk in enumerate(_split_message(text)):
        reply_to = reply_to_message_id if index == 0 else None
        try:
            last_id = await _send(chunk, parse_mode="HTML", reply_to_message_id=reply_to)
        except _TelegramBadRequestError as e:
            logger.warning("Telegram rejected HTML reply (%s); retrying as plain text", e.description)
            last_id = await _send(_strip_tags(chunk), parse_mode=None, reply_to_message_id=reply_to)
    return last_id


async def send_alert(text: str) -> str | None:
    """Send a plain-text alert. No parse_mode so reserved characters render literally."""
    return await _send(text, parse_mode=None)


def parse_update(update: dict[str, Any]) -> IncomingMessage | None:
    """Return a message from the configured chat, or None to ignore the update.

    Non-text messages from the configured chat are returned with empty ``text``
    so the listener can send a short hint. Updates from other chats are dropped.
    """
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id", ""))
    expected = str(settings.telegram_chat_id)
    if not chat_id or chat_id != expected:
        logger.info("Ignoring Telegram update from chat_id=%s", chat_id or "?")
        return None
    raw_text = message.get("text")
    text = raw_text.strip() if isinstance(raw_text, str) else ""
    update_id = update.get("update_id")
    message_id = message.get("message_id")
    if update_id is None or message_id is None:
        return None
    return IncomingMessage(
        update_id=int(update_id),
        message_id=int(message_id),
        chat_id=chat_id,
        text=text,
    )


async def get_updates(
    offset: int | None,
    *,
    poll_seconds: int = _POLL_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Long-poll Telegram getUpdates. ``poll_seconds=0`` is a non-blocking drain."""
    payload: dict[str, Any] = {
        "timeout": poll_seconds,
        "allowed_updates": ["message"],
    }
    if offset is not None:
        payload["offset"] = offset
    http_timeout = poll_seconds + 15 if poll_seconds else 15
    async with httpx.AsyncClient(timeout=http_timeout) as client:
        response = await client.post(_api_url("getUpdates"), json=payload)
    data = _require_ok(response, "getUpdates")
    result = data.get("result") or []
    return result if isinstance(result, list) else []


async def acknowledge_pending() -> int | None:
    """Drop updates already waiting at startup so we do not reply to stale DMs.

    Returns the next offset to poll from, or None if the queue was empty.
    """
    updates = await get_updates(None, poll_seconds=0)
    if not updates:
        return None
    last_id = max(int(u["update_id"]) for u in updates if u.get("update_id") is not None)
    return last_id + 1


async def _send(
    text: str,
    *,
    parse_mode: str | None,
    reply_to_message_id: int | None = None,
) -> str | None:
    chat_id = settings.telegram_chat_id
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": _truncate(text),
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
        payload["allow_sending_without_reply"] = True

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(_api_url("sendMessage"), json=payload)

    data = _require_ok(response, "sendMessage")
    message_id = data.get("result", {}).get("message_id")
    return str(message_id) if message_id is not None else None
