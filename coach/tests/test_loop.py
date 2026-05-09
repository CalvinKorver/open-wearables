"""Tests for the agent loop's tool-spec mapping and tool dispatching."""

from typing import Any

import pytest
from anthropic.types import TextBlock, ToolUseBlock

from app.agent import loop as agent_loop
from app.agent.mcp_client import ToolSpec


def test_build_tool_params_filters_to_allowed_tools():
    specs = [
        ToolSpec(name="get_workout_events", description="w", input_schema={"type": "object"}),
        ToolSpec(name="get_sleep_summary", description="s", input_schema={"type": "object"}),
        ToolSpec(name="get_users", description="u", input_schema={"type": "object"}),
        ToolSpec(name="some_other", description="x", input_schema={}),
    ]
    params = agent_loop._build_tool_params(specs)

    names = {p["name"] for p in params}
    assert names == {"get_workout_events"}


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
