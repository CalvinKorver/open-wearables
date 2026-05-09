"""Telegram outbound channel.

We send with parse_mode=HTML rather than MarkdownV2. HTML only requires escaping
three characters (<, >, &) so the model produces correct markup far more
reliably than MarkdownV2, where every literal `.` or `!` would need a backslash.

If the HTML send is still rejected for any reason (e.g. the model emitted an
unbalanced tag), we fall back to a plain-text send with no parse_mode so the
briefing always reaches the user.

Two send paths:
- send_briefing: the daily message; expects HTML already produced by the model.
- send_alert: a plain-text fatal-error notice (HTML-escaped before sending).
"""

import html
from logging import getLogger
from typing import Any

import httpx

from app.config import settings

logger = getLogger(__name__)


_TELEGRAM_API_BASE = "https://api.telegram.org"
_TELEGRAM_MAX_LEN = 4096

_TELEGRAM_BAD_REQUEST = 400


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


async def send_briefing(text: str) -> str | None:
    """Send the daily briefing as HTML; fall back to plain text if HTML is rejected."""
    try:
        return await _send(text, parse_mode="HTML")
    except _TelegramBadRequest as e:
        logger.warning("Telegram rejected HTML briefing (%s); retrying as plain text", e.description)
        return await _send(_strip_tags(text), parse_mode=None)


async def send_alert(text: str) -> str | None:
    """Send a plain-text alert. No parse_mode so reserved characters render literally."""
    return await _send(text, parse_mode=None)


class _TelegramBadRequest(Exception):
    """Raised when Telegram returns a 400 (e.g. parse_mode formatting issue)."""

    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.description = description


async def _send(text: str, *, parse_mode: str | None) -> str | None:
    token = settings.telegram_bot_token.get_secret_value()
    chat_id = settings.telegram_chat_id
    url = f"{_TELEGRAM_API_BASE}/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": _truncate(text),
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload)

    if response.status_code == _TELEGRAM_BAD_REQUEST:
        try:
            description = response.json().get("description", response.text)
        except ValueError:
            description = response.text
        logger.error("Telegram sendMessage 400: %s", description)
        raise _TelegramBadRequest(description)

    if response.status_code != 200:
        logger.error("Telegram sendMessage failed: status=%s body=%s", response.status_code, response.text)
        response.raise_for_status()

    data = response.json()
    if not data.get("ok"):
        logger.error("Telegram sendMessage returned ok=false: %s", data)
        raise RuntimeError(f"Telegram API error: {data.get('description')}")

    message_id = data.get("result", {}).get("message_id")
    return str(message_id) if message_id is not None else None
