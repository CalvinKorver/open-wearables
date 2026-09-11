import logging

from app.logging_utils import SecretRedactingFilter, install_secret_redaction, redact_secrets


def test_redact_secrets_masks_telegram_api_url() -> None:
    url = "https://api.telegram.org/bot8242510840:AAEmyvjSJEhWJ5ToGFL7xR6DI244nOYEnSg/getMe"
    assert redact_secrets(url) == "https://api.telegram.org/bot***/getMe"


def test_redact_secrets_masks_bot_token_outside_url() -> None:
    text = "token bot8242510840:AAEmyvjSJEhWJ5ToGFL7xR6DI244nOYEnSg leaked"
    assert redact_secrets(text) == "token bot*** leaked"


def test_secret_redacting_filter_masks_httpx_style_args() -> None:
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='HTTP Request: %s %s "%s %d %s"',
        args=(
            "GET",
            "https://api.telegram.org/bot8242510840:AAEmyvjSJEhWJ5ToGFL7xR6DI244nOYEnSg/getMe",
            "HTTP/1.1",
            200,
            "OK",
        ),
        exc_info=None,
    )
    assert SecretRedactingFilter().filter(record) is True
    assert "AAEmyvjSJEhWJ5ToGFL7xR6DI244nOYEnSg" not in record.getMessage()
    assert "https://api.telegram.org/bot***/getMe" in record.getMessage()


def test_install_secret_redaction_is_idempotent() -> None:
    root = logging.getLogger()
    before = sum(isinstance(item, SecretRedactingFilter) for item in root.filters)
    install_secret_redaction()
    install_secret_redaction()
    after = sum(isinstance(item, SecretRedactingFilter) for item in root.filters)
    assert after == before + 1
    root.removeFilter(next(item for item in root.filters if isinstance(item, SecretRedactingFilter)))
