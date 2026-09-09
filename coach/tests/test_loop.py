"""Tests for the agent loop's tool-spec mapping and tool dispatching."""

from typing import Any

import pytest
from anthropic.types import TextBlock, ToolUseBlock

from app.agent import loop as agent_loop
from app.agent.mcp_client import ToolSpec
from app.agent.prompts import CHAT_ALLOWED_TOOLS
from app.storage import db
from app.storage.db import MemoryKind


def test_build_tool_params_filters_to_allowed_tools():
    specs = [
        ToolSpec(name="get_workout_events", description="w", input_schema={"type": "object"}),
        ToolSpec(name="get_sleep_summary", description="s", input_schema={"type": "object"}),
        ToolSpec(name="get_users", description="u", input_schema={"type": "object"}),
        ToolSpec(name="some_other", description="x", input_schema={}),
    ]
    params = agent_loop._build_tool_params(specs)

    names = {p["name"] for p in params}
    assert names == {"get_workout_events", "get_sleep_summary"}


def test_build_tool_params_supplies_default_schema_when_missing():
    specs = [ToolSpec(name="get_workout_events", description="d", input_schema={})]
    params = agent_loop._build_tool_params(specs)
    assert len(params) == 1
    assert params[0]["input_schema"] == {"type": "object", "properties": {}}


class _FakeMessage:
    """Stand-in for anthropic.types.Message that exposes only the .content attribute used by helpers."""

    def __init__(self, content: list[Any]) -> None:
        self.content = content


def test_extract_text_concatenates_text_blocks():
    msg = _FakeMessage(
        [
            TextBlock(type="text", text="Hello", citations=None),
            TextBlock(type="text", text="World", citations=None),
        ]
    )
    assert agent_loop._extract_text(msg) == "Hello\nWorld"


def test_extract_tool_uses_returns_only_tool_use_blocks():
    msg = _FakeMessage(
        [
            TextBlock(type="text", text="thinking", citations=None),
            ToolUseBlock(type="tool_use", id="tu_1", name="get_sleep_summary", input={"x": 1}),
        ]
    )
    uses = agent_loop._extract_tool_uses(msg)
    assert len(uses) == 1
    assert uses[0].name == "get_sleep_summary"


class _FakeSession:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        return self._response


@pytest.mark.asyncio
async def test_dispatch_tool_allows_sleep_summary():
    tu = ToolUseBlock(
        type="tool_use",
        id="tu_sleep",
        name="get_sleep_summary",
        input={"user_id": "u", "start_date": "2026-05-08", "end_date": "2026-05-08"},
    )
    session = _FakeSession({"records": [{"date": "2026-05-08", "duration_minutes": 480}]})

    result = await agent_loop._dispatch_tool(session, tu)

    assert result.get("is_error") is False
    assert session.calls == [
        ("get_sleep_summary", {"user_id": "u", "start_date": "2026-05-08", "end_date": "2026-05-08"}),
    ]


@pytest.mark.asyncio
async def test_dispatch_tool_allows_known_tool():
    tu = ToolUseBlock(
        type="tool_use",
        id="tu_1",
        name="get_workout_events",
        input={"user_id": "u", "start_date": "2026-05-07", "end_date": "2026-05-07"},
    )
    session = _FakeSession({"records": [], "summary": {}})

    result = await agent_loop._dispatch_tool(session, tu)

    assert result["tool_use_id"] == "tu_1"
    assert result.get("is_error") is False
    assert session.calls == [
        ("get_workout_events", {"user_id": "u", "start_date": "2026-05-07", "end_date": "2026-05-07"}),
    ]


@pytest.mark.asyncio
async def test_dispatch_tool_blocks_unknown_tool():
    tu = ToolUseBlock(type="tool_use", id="tu_x", name="get_users", input={})
    session = _FakeSession({})

    result = await agent_loop._dispatch_tool(session, tu)

    assert result["is_error"] is True
    assert "not available" in result["content"]
    assert session.calls == []


def test_history_to_messages_merges_and_drops_leading_assistant():
    messages = agent_loop.history_to_messages(
        [
            ("assistant", "stale"),
            ("user", "one"),
            ("user", "two"),
            ("assistant", "ok"),
            ("system", "ignore me"),
            ("assistant", ""),
        ]
    )
    assert messages == [
        {"role": "user", "content": "one\ntwo"},
        {"role": "assistant", "content": "ok"},
    ]


def test_build_tool_params_can_use_chat_allowlist():
    specs = [
        ToolSpec(name="get_activity_summary", description="a", input_schema={"type": "object"}),
        ToolSpec(name="get_users", description="u", input_schema={}),
        ToolSpec(name="get_workout_events", description="w", input_schema={"type": "object"}),
    ]
    params = agent_loop._build_tool_params(specs, CHAT_ALLOWED_TOOLS)
    names = {p["name"] for p in params}
    assert names == {"get_activity_summary", "get_workout_events"}


@pytest.mark.asyncio
async def test_dispatch_tool_allows_activity_when_chat_allowlist():
    tu = ToolUseBlock(
        type="tool_use",
        id="tu_act",
        name="get_activity_summary",
        input={"user_id": "u", "start_date": "2026-05-01", "end_date": "2026-05-07"},
    )
    session = _FakeSession({"records": []})
    result = await agent_loop._dispatch_tool(session, tu, CHAT_ALLOWED_TOOLS)
    assert result.get("is_error") is False
    assert session.calls == [
        ("get_activity_summary", {"user_id": "u", "start_date": "2026-05-01", "end_date": "2026-05-07"}),
    ]


@pytest.mark.asyncio
async def test_dispatch_tool_marks_error_when_tool_returns_error():
    tu = ToolUseBlock(
        type="tool_use",
        id="tu_2",
        name="get_workout_events",
        input={"user_id": "u", "start_date": "2026-05-07", "end_date": "2026-05-07"},
    )
    session = _FakeSession({"error": "User not found"})

    result = await agent_loop._dispatch_tool(session, tu)

    assert result["is_error"] is True


def test_with_memory_omits_block_when_empty() -> None:
    db.init_db()
    with db.session() as s:
        s.query(db.MemoryItem).delete()
        s.commit()
    assert agent_loop._with_memory("BASE") == "BASE"


def test_chat_system_prompt_includes_durable_profile() -> None:
    db.init_db()
    with db.session() as s:
        s.query(db.MemoryItem).delete()
        s.commit()
    db.add_memory(MemoryKind.GOAL, "Race 70.3")
    prompt = agent_loop._chat_system_prompt()
    assert "Durable profile" in prompt
    assert "Race 70.3" in prompt
    assert "user_id:" in prompt
