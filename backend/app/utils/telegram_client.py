import logging

import httpx

from app.config import settings
from app.utils.structured_logging import log_structured

logger = logging.getLogger(__name__)

TELEGRAM_MESSAGE_MAX_LENGTH = 4096


def is_telegram_configured() -> bool:
    """Return True when Telegram bot credentials are set."""
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def send_message(text: str) -> bool:
    """Send a text message via the Telegram Bot API.

    Args:
        text: Message body (truncated to Telegram's 4096-character limit).

    Returns:
        True if the message was sent successfully, False otherwise.
    """
    if not is_telegram_configured():
        log_structured(
            logger,
            "warning",
            "Telegram not configured, skipping message send",
            provider="telegram",
            task="send_message",
        )
        return False

    if len(text) > TELEGRAM_MESSAGE_MAX_LENGTH:
        log_structured(
            logger,
            "warning",
            f"Telegram message truncated from {len(text)} to {TELEGRAM_MESSAGE_MAX_LENGTH} characters",
            provider="telegram",
            task="send_message",
        )
        text = text[: TELEGRAM_MESSAGE_MAX_LENGTH - 3] + "..."

    token = settings.telegram_bot_token.get_secret_value()  # ty:ignore[unresolved-attribute]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": settings.telegram_chat_id, "text": text}

    try:
        response = httpx.post(url, json=payload, timeout=30.0)
        response.raise_for_status()
        log_structured(
            logger,
            "info",
            "Telegram message sent successfully",
            provider="telegram",
            task="send_message",
        )
        return True
    except Exception as e:
        log_structured(
            logger,
            "error",
            f"Failed to send Telegram message: {e}",
            provider="telegram",
            task="send_message",
        )
        return False
