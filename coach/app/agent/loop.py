"""Anthropic tool-use loop driving the OW MCP server.

The loop wraps the standard Claude tool-use protocol: send messages, if the
model emits tool_use blocks, dispatch them to the MCP session and feed back
tool_result blocks, repeat until the model stops calling tools.
"""

from datetime import date
from logging import getLogger
from typing import Any

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
from app.agent.prompts import ALLOWED_TOOLS, SYSTEM_PROMPT, user_prompt
from app.config import settings

logger = getLogger(__name__)

MAX_ITERATIONS = 6
MAX_TOKENS = 2048


def _build_tool_params(specs: list[ToolSpec]) -> list[ToolParam]:
    """Convert MCP tool specs into the Anthropic tools=[] schema, filtered to ALLOWED_TOOLS."""
    params: list[ToolParam] = []
    for spec in specs:
        if spec.name not in ALLOWED_TOOLS:
            continue
        params.append(
            ToolParam(
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema or {"type": "object", "properties": {}},
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
    session: McpSession, tool_use: ToolUseBlock
) -> ToolResultBlockParam:
    """Run a single tool_use against MCP and return a tool_result block to feed back to Claude."""
    name = tool_use.name
    if name not in ALLOWED_TOOLS:
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
    import json

    return json.dumps(data, default=str)


async def generate_briefing(session: McpSession, local_date: date) -> str:
    """Run the agent loop and return the final assistant text for `local_date`."""
    anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())

    tool_specs = await session.list_tools()
    tools = _build_tool_params(tool_specs)
    advertised = [t.name for t in tool_specs]
    logger.info(
        "Briefing loop date=%s tz=%s user_id=%s advertised_tools=%s enabled_tools=%s model=%s",
        local_date.isoformat(),
        settings.briefing_timezone,
        settings.ow_user_id,
        advertised,
        sorted(p["name"] for p in tools),
        settings.anthropic_model,
    )
    if not tools:
        raise RuntimeError("OW MCP server did not advertise any of the expected briefing tools")

    messages: list[MessageParam] = [
        {"role": "user", "content": user_prompt(local_date, settings.ow_user_id)},
    ]

    for iteration in range(MAX_ITERATIONS):
        response = await anthropic.messages.create(
            model=settings.anthropic_model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )
        logger.info(
            "Model iteration=%s stop_reason=%s input_tokens=%s output_tokens=%s",
            iteration,
            response.stop_reason,
            getattr(response.usage, "input_tokens", None),
            getattr(response.usage, "output_tokens", None),
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            text = _extract_text(response)
            if not text:
                raise RuntimeError(f"Model stopped with reason {response.stop_reason} and produced no text")
            logger.info("Briefing text chars=%s", len(text))
            return text

        tool_uses = _extract_tool_uses(response)
        if not tool_uses:
            raise RuntimeError("stop_reason=tool_use but no tool_use blocks present")

        results: list[ToolResultBlockParam] = []
        for tu in tool_uses:
            logger.info("Calling MCP tool: %s args=%s", tu.name, tu.input)
            results.append(await _dispatch_tool(session, tu))
        messages.append({"role": "user", "content": results})

    raise RuntimeError(f"Agent loop did not converge within {MAX_ITERATIONS} iterations")
