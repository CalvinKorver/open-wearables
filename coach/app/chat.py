"""Handle inbound Telegram messages to the health coach."""

import asyncio
from logging import getLogger

from app.agent.loop import generate_reply
from app.agent.mcp_client import open_mcp_client
from app.briefing import run_for_date, yesterday_local
from app.channels.telegram import IncomingMessage, send_alert, send_chat_action, send_reply
from app.storage import db
from app.storage.db import MemoryFullError, MemoryKind, MemoryTooLongError

logger = getLogger(__name__)

HELP_TEXT = (
    "<b>Open Wearables coach</b>\n"
    "\n"
    "I can pull your wearable data and answer questions about sleep, workouts, and activity.\n"
    "\n"
    "Commands:\n"
    "- /brief — send yesterday's daily briefing now\n"
    "- /goal &lt;text&gt; — save a durable goal\n"
    "- /fact &lt;text&gt; — save a durable fact\n"
    "- /goals — list goals\n"
    "- /facts — list facts\n"
    "- /memory — list goals and facts\n"
    "- /forget &lt;id|goals|facts|all&gt; — remove durable memory\n"
    "- /clear — forget this chat's recent history (not goals/facts)\n"
    "- /help — this message\n"
    "\n"
    'Or just ask, e.g. "How did I sleep this week?"'
)

_FORGET_USAGE = "Usage: /forget <id|goals|facts|all>"

# Serialize briefing + chat so two MCP stdio subprocesses are not spawned at once.
_busy = asyncio.Lock()


def normalize_command(text: str) -> str:
    """Strip a @botname suffix from a slash command (``/help@MyBot`` -> ``/help``)."""
    if not text.startswith("/"):
        return text
    command, _, rest = text.partition(" ")
    if "@" in command:
        command = command.split("@", 1)[0]
    return f"{command} {rest}".strip() if rest else command


def _format_memory_list(kind: MemoryKind | None = None) -> str:
    items = db.list_memory(kind)
    if kind is None:
        goals = [i for i in items if i.kind == MemoryKind.GOAL]
        facts = [i for i in items if i.kind == MemoryKind.FACT]
        if not goals and not facts:
            return "No goals or facts saved. Use /goal or /fact to add some."
        parts: list[str] = []
        if goals:
            parts.append("Goals:\n" + "\n".join(f"- #{i.id}: {i.content}" for i in goals))
        else:
            parts.append("Goals:\n(none)")
        if facts:
            parts.append("Facts:\n" + "\n".join(f"- #{i.id}: {i.content}" for i in facts))
        else:
            parts.append("Facts:\n(none)")
        return "\n\n".join(parts)

    label = "Goals" if kind == MemoryKind.GOAL else "Facts"
    if not items:
        return f"No {kind.value}s saved."
    return f"{label}:\n" + "\n".join(f"- #{i.id}: {i.content}" for i in items)


async def _handle_memory_command(text: str, message_id: int) -> bool:
    """Handle durable-memory slash commands. Returns True if consumed."""
    if text == "/goals":
        await send_reply(_format_memory_list(MemoryKind.GOAL), reply_to_message_id=message_id)
        return True
    if text == "/facts":
        await send_reply(_format_memory_list(MemoryKind.FACT), reply_to_message_id=message_id)
        return True
    if text == "/memory":
        await send_reply(_format_memory_list(), reply_to_message_id=message_id)
        return True

    if text == "/goal" or text.startswith("/goal "):
        content = text[len("/goal") :].strip()
        if not content:
            await send_reply("Usage: /goal <text>", reply_to_message_id=message_id)
            return True
        try:
            item = db.add_memory(MemoryKind.GOAL, content)
        except MemoryTooLongError:
            await send_reply(
                f"Too long. Goals must be at most {db.MAX_MEMORY_CONTENT_CHARS} characters.",
                reply_to_message_id=message_id,
            )
            return True
        except MemoryFullError as e:
            await send_reply(str(e), reply_to_message_id=message_id)
            return True
        await send_reply(f"Saved goal #{item.id}: {item.content}", reply_to_message_id=message_id)
        return True

    if text == "/fact" or text.startswith("/fact "):
        content = text[len("/fact") :].strip()
        if not content:
            await send_reply("Usage: /fact <text>", reply_to_message_id=message_id)
            return True
        try:
            item = db.add_memory(MemoryKind.FACT, content)
        except MemoryTooLongError:
            await send_reply(
                f"Too long. Facts must be at most {db.MAX_MEMORY_CONTENT_CHARS} characters.",
                reply_to_message_id=message_id,
            )
            return True
        except MemoryFullError as e:
            await send_reply(str(e), reply_to_message_id=message_id)
            return True
        await send_reply(f"Saved fact #{item.id}: {item.content}", reply_to_message_id=message_id)
        return True

    if text == "/forget" or text.startswith("/forget "):
        arg = text[len("/forget") :].strip().lower()
        if not arg:
            await send_reply(_FORGET_USAGE, reply_to_message_id=message_id)
            return True
        if arg == "all":
            n = db.clear_memory()
            await send_reply(f"Forgot {n} memory item(s).", reply_to_message_id=message_id)
            return True
        if arg == "goals":
            n = db.clear_memory(MemoryKind.GOAL)
            await send_reply(f"Forgot {n} goal(s).", reply_to_message_id=message_id)
            return True
        if arg == "facts":
            n = db.clear_memory(MemoryKind.FACT)
            await send_reply(f"Forgot {n} fact(s).", reply_to_message_id=message_id)
            return True
        if arg.isdigit():
            item_id = int(arg)
            if db.delete_memory(item_id):
                await send_reply(f"Forgot #{item_id}.", reply_to_message_id=message_id)
            else:
                await send_reply(f"No memory item #{item_id}.", reply_to_message_id=message_id)
            return True
        await send_reply(_FORGET_USAGE, reply_to_message_id=message_id)
        return True

    return False


async def handle_incoming(message: IncomingMessage) -> None:
    """Route one inbound Telegram message: commands, hints, or a health-data reply."""
    if not message.text:
        await send_reply(
            "I only read text. Ask about sleep, workouts, or activity — or send /help.",
            reply_to_message_id=message.message_id,
        )
        return

    text = normalize_command(message.text)
    if text in {"/start", "/help"}:
        await send_reply(HELP_TEXT, reply_to_message_id=message.message_id)
        return
    if text == "/clear":
        db.clear_conversation()
        await send_reply(
            "Cleared recent chat history. Goals and facts are unchanged — see /memory.",
            reply_to_message_id=message.message_id,
        )
        return
    if text == "/brief":
        async with _busy:
            await run_for_date(yesterday_local(), force=True)
        return
    if await _handle_memory_command(text, message.message_id):
        return

    async with _busy:
        await _answer(message, text)


async def _answer(message: IncomingMessage, text: str) -> None:
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(stop_typing))
    try:
        history = db.get_conversation_turns()
        async with open_mcp_client() as session:
            reply = await generate_reply(session, text, history)
    except Exception as e:
        logger.exception("Chat reply failed")
        await send_alert(f"Coach reply failed: {e}")
        return
    finally:
        stop_typing.set()
        await typing_task

    db.append_conversation_turn("user", text)
    db.append_conversation_turn("assistant", reply)
    await send_reply(reply, reply_to_message_id=message.message_id)


async def _keep_typing(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await send_chat_action("typing")
        except Exception:
            logger.debug("sendChatAction failed", exc_info=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=4)
        except TimeoutError:
            continue
