import httpx
import pytest

from app.channels.telegram import (
    IncomingMessage,
    TelegramAPIError,
    _split_message,
    _strip_tags,
    _TelegramBadRequestError,
    _truncate,
    escape_html,
    parse_update,
    verify_bot,
)


def test_escape_html_escapes_lt_gt_amp():
    assert escape_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_escape_html_leaves_safe_chars_alone():
    src = "Steps: 12,345 (great!). Heart rate up 4%."
    assert escape_html(src) == src


def test_strip_tags_removes_html_and_unescapes_entities():
    src = "<b>Yesterday</b>: ran 5km &amp; slept 7h"
    assert _strip_tags(src) == "Yesterday: ran 5km & slept 7h"


def test_strip_tags_handles_no_tags():
    assert _strip_tags("just plain text") == "just plain text"


def test_truncate_short_text_unchanged():
    assert _truncate("short", limit=10) == "short"


def test_truncate_long_text_appends_ellipsis():
    out = _truncate("x" * 100, limit=10)
    assert len(out) == 10
    assert out.endswith("\u2026")


def test_split_message_short_text_single_chunk():
    assert _split_message("hello") == ["hello"]


def test_split_message_splits_on_newline():
    text = ("a" * 20) + "\n" + ("b" * 20)
    chunks = _split_message(text, limit=25)
    assert len(chunks) == 2
    assert chunks[0] == "a" * 20
    assert chunks[1] == "b" * 20


def test_split_message_hard_cuts_when_no_break():
    chunks = _split_message("x" * 50, limit=20)
    assert "".join(chunks) == "x" * 50
    assert all(len(c) <= 20 for c in chunks)


def test_parse_update_extracts_text_from_configured_chat():
    incoming = parse_update(
        {
            "update_id": 99,
            "message": {
                "message_id": 7,
                "chat": {"id": 1234567},
                "text": "  How did I sleep?  ",
            },
        }
    )
    assert incoming == IncomingMessage(
        update_id=99,
        message_id=7,
        chat_id="1234567",
        text="How did I sleep?",
    )


def test_parse_update_ignores_other_chats():
    incoming = parse_update(
        {
            "update_id": 1,
            "message": {"message_id": 1, "chat": {"id": 999}, "text": "hi"},
        }
    )
    assert incoming is None


def test_parse_update_empty_text_for_non_text_from_configured_chat():
    incoming = parse_update(
        {
            "update_id": 2,
            "message": {"message_id": 3, "chat": {"id": 1234567}, "photo": [{}]},
        }
    )
    assert incoming is not None
    assert incoming.text == ""


def test_parse_update_ignores_callback_and_edits():
    assert parse_update({"update_id": 1, "edited_message": {"message_id": 1}}) is None
    assert parse_update({"update_id": 1, "callback_query": {}}) is None


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[tuple[str, str]] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append(("get", url))
        return self._response

    async def post(self, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append(("post", url))
        return self._response


@pytest.mark.asyncio
async def test_verify_bot_returns_get_me_result(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeAsyncClient(_FakeResponse(200, {"ok": True, "result": {"username": "ow_coach_bot", "id": 1}}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    result = await verify_bot()
    assert result["username"] == "ow_coach_bot"
    assert client.calls and client.calls[0][0] == "get"
    assert client.calls[0][1].endswith("/getMe")


@pytest.mark.asyncio
async def test_verify_bot_raises_on_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeAsyncClient(_FakeResponse(401, {"ok": False, "description": "Unauthorized"}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    with pytest.raises(TelegramAPIError, match="TELEGRAM_BOT_TOKEN"):
        await verify_bot()


def test_telegram_bad_request_stores_description() -> None:
    err = _TelegramBadRequestError("can't parse entities")
    assert err.description == "can't parse entities"
