"""Logging helpers that keep secrets out of coach process output."""

from __future__ import annotations

import logging
import re
from typing import Any

# Telegram bot API tokens appear in request URLs as /bot<token>/.
_TELEGRAM_BOT_TOKEN_RE = re.compile(r"(https?://api\.telegram\.org/bot)([^/\s]+)(/)")
_TELEGRAM_BOT_PREFIX_RE = re.compile(r"\bbot(\d+:[A-Za-z0-9_-]+)\b")


def redact_secrets(text: str) -> str:
    """Replace Telegram bot tokens in free-form log text with a stable placeholder."""
    redacted = _TELEGRAM_BOT_TOKEN_RE.sub(r"\1***\3", text)
    return _TELEGRAM_BOT_PREFIX_RE.sub("bot***", redacted)


class SecretRedactingFilter(logging.Filter):
    """Redact known secret patterns from every log record before emission."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(_stringify(record.msg))
        if record.args:
            if isinstance(record.args, dict):
                record.args = {key: _redact_value(value) for key, value in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(_redact_value(arg) for arg in record.args)
            else:
                record.args = _redact_value(record.args)
        return True


def _stringify(value: Any) -> str:
    return value if isinstance(value, str) else str(value)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secrets(value)
    return value


def install_secret_redaction() -> None:
    """Attach the redacting filter to the root logger once."""
    root = logging.getLogger()
    if any(isinstance(existing, SecretRedactingFilter) for existing in root.filters):
        return
    root.addFilter(SecretRedactingFilter())
