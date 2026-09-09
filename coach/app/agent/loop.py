"""Anthropic tool-use loop driving the OW MCP server.

The loop wraps the standard Claude tool-use protocol: send messages, if the
model emits tool_use blocks, dispatch them to the MCP session and feed back
tool_result blocks, repeat until the model stops calling tools.
"""

import json
from datetime import date, datetime
from logging import getLogger
from typing import Any, Literal, cast

from anthropic import AsyncAnthropic
from anthropic.types import (
    Message,
    MessageParam,
    TextBlock,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlock,
)

from app.agent.mcp_client import McpSession, ToolSpec
from app.agent.prompts import (
    ALLOWED_TOOLS,
    CHAT_ALLOWED_TOOLS,
    CHAT_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    user_prompt,
)
from app.config import settings
from app.storage import db

logger = getLogger(__name__)

MAX_ITERATIONS = 6
MAX_CHAT_ITERATIONS = 8
MAX_TOKENS = 2048


def _with_memory(system: str) -> str:
    block = db.format_memory_block()
    if not block:
        return system
    return f"{system}\n{block}\n"


def _build_tool_params(
    specs: list[ToolSpec],
    allowed: frozenset[str] | None = None,
) -> list[ToolParam]:
    """Convert MCP tool specs into the Anthropic tools=[] schema, filtered to allowed names."""
    allowed_tools = allowed if allowed is not None else ALLOWED_TOOLS
    params: list[ToolParam] = []
    for spec in specs:
        if spec.name not in allowed_tools:
            continue
        params.append(
            ToolParam(
                name=spec.name,
                description=spec.description,
                input_schema=cast(
                    dict[str, object],
                    spec.input_schema or {"type": "object", "properties": {}},
                ),
            )
        )
    return params


def _extract_text(message: Message) -> str:
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            parts.append(block.text)
    return "\n".join(p for p in parts if p).strip()


def _extract_tool_uses(message: Message) -> list[ToolUseBlock]:
    return [b for b in message.content if isinstance(b, ToolUseBlock)]


def _record_line(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": record.get("type") or record.get("date"),
        "start": record.get("start_local") or record.get("start_datetime"),
        "source": record.get("source"),
        "duration": record.get("duration_seconds") or record.get("duration_minutes"),
    }


def _summarize_tool_result(name: str, args: dict[str, Any], result: dict[str, Any]) -> None:
    """Log a compact view of MCP output so empty vs populated days are diagnosable."""
    if result.get("error"):
        logger.info(
            "MCP %s error args=%s error=%s details=%s",
            name,
            args,
            result.get("error"),
            result.get("details"),
        )
        return

    records = result.get("records")
    if not isinstance(records, list):
        logger.info("MCP %s args=%s keys=%s", name, args, sorted(result.keys()))
        return

    logger.info(
        "MCP %s args=%s n_records=%s summary=%s records=%s",
        name,
        args,
        len(records),
        result.get("summary"),
        [_record_line(r) for r in records if isinstance(r, dict)],
    )


async def _dispatch_tool(
    session: McpSession,
    tool_use: ToolUseBlock,
    allowed: frozenset[str] | None = None,
) -> ToolResultBlockParam:
    """Run a single tool_use against MCP and return a tool_result block to feed back to Claude."""
    allowed_tools = allowed if allowed is not None else ALLOWED_TOOLS
    name = tool_use.name
    if name not in allowed_tools:
        logger.info("Blocked MCP tool: %s", name)
        return ToolResultBlockParam(
            type="tool_result",
            tool_use_id=tool_use.id,
            content=f"Tool {name} is not available to this agent.",
            is_error=True,
        )
    try:
        args = tool_use.input if isinstance(tool_use.input, dict) else {}
        result = await session.call_tool(name, args)
        _summarize_tool_result(name, args, result)
        is_error = "error" in result and len(result) <= 2
        return ToolResultBlockParam(
            type="tool_result",
            tool_use_id=tool_use.id,
            content=_json_safe(result),
            is_error=is_error,
        )
    except Exception as e:
        logger.exception("MCP tool call failed: %s", name)
        return ToolResultBlockParam(
            type="tool_result",
            tool_use_id=tool_use.id,
            content=f"Tool {name} raised: {e}",
            is_error=True,
        )


def _json_safe(data: dict[str, Any]) -> str:
    """Anthropic tool_result content accepts a string. We pass JSON for the model to parse."""
    return json.dumps(data, default=str)


def history_to_messages(history: list[tuple[str, str]]) -> list[MessageParam]:
    """Turn stored (role, content) pairs into a valid Anthropic transcript.

    Consecutive same-role turns are merged. A leading assistant turn is dropped
    so the first message is always ``user``.
    """
    messages: list[MessageParam] = []
    for role, content in history:
        if role not in {"user", "assistant"}:
            continue
        text = content.strip()
        if not text:
            continue
        typed_role = cast(Literal["user", "assistant"], role)
        if messages and messages[-1]["role"] == typed_role:
            previous = messages[-1]["content"]
            if isinstance(previous, str):
                messages[-1] = {"role": typed_role, "content": previous + "\n" + text}
            continue
        messages.append({"role": typed_role, "content": text})
    if messages and messages[0]["role"] != "user":
        messages = messages[1:]
    return messages


def _chat_system_prompt() -> str:
    now = datetime.now(settings.tz)
    base = (
        f"{CHAT_SYSTEM_PROMPT}\n"
        f"user_id: {settings.ow_user_id}\n"
        f"User local timezone (IANA): {settings.briefing_timezone}\n"
        f"Today's local date: {now.date().isoformat()}\n"
        f"Current local time: {now.strftime('%H:%M')}\n"
    )
    return _with_memory(base)


async def _run_agent(
    session: McpSession,
    *,
    system: str,
    allowed_tools: frozenset[str],
    messages: list[MessageParam],
    max_iterations: int,
    log_label: str,
) -> str:
    anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())

    tool_specs = await session.list_tools()
    tools = _build_tool_params(tool_specs, allowed_tools)
    advertised = [t.name for t in tool_specs]
    logger.info(
        "%s tz=%s user_id=%s advertised_tools=%s enabled_tools=%s model=%s",
        log_label,
        settings.briefing_timezone,
        settings.ow_user_id,
        advertised,
        sorted(p["name"] for p in tools),
        settings.anthropic_model,
    )
    if not tools:
        raise RuntimeError("OW MCP server did not advertise any of the expected tools")

    working = list(messages)
    for iteration in range(max_iterations):
        response = await anthropic.messages.create(
            model=settings.anthropic_model,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=tools,
            messages=working,
        )
        logger.info(
            "Model iteration=%s stop_reason=%s input_tokens=%s output_tokens=%s",
            iteration,
            response.stop_reason,
            getattr(response.usage, "input_tokens", None),
            getattr(response.usage, "output_tokens", None),
        )

        working.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            text = _extract_text(response)
            if not text:
                raise RuntimeError(f"Model stopped with reason {response.stop_reason} and produced no text")
            logger.info("%s text chars=%s", log_label, len(text))
            return text

        tool_uses = _extract_tool_uses(response)
        if not tool_uses:
            raise RuntimeError("stop_reason=tool_use but no tool_use blocks present")

        results: list[ToolResultBlockParam] = []
        for tu in tool_uses:
            logger.info("Calling MCP tool: %s args=%s", tu.name, tu.input)
            results.append(await _dispatch_tool(session, tu, allowed_tools))
        working.append({"role": "user", "content": results})

    raise RuntimeError(f"Agent loop did not converge within {max_iterations} iterations")


async def generate_briefing(session: McpSession, local_date: date) -> str:
    """Run the agent loop and return the final assistant text for `local_date`."""
    return await _run_agent(
        session,
        system=_with_memory(SYSTEM_PROMPT),
        allowed_tools=ALLOWED_TOOLS,
        messages=[{"role": "user", "content": user_prompt(local_date, settings.ow_user_id)}],
        max_iterations=MAX_ITERATIONS,
        log_label=f"Briefing loop date={local_date.isoformat()}",
    )


async def generate_reply(
    session: McpSession,
    user_text: str,
    history: list[tuple[str, str]],
) -> str:
    """Answer an inbound Telegram message using MCP tools and recent chat history."""
    messages = history_to_messages(history)
    messages.append({"role": "user", "content": user_text})
    return await _run_agent(
        session,
        system=_chat_system_prompt(),
        allowed_tools=CHAT_ALLOWED_TOOLS,
        messages=messages,
        max_iterations=MAX_CHAT_ITERATIONS,
        log_label="Chat loop",
    )
