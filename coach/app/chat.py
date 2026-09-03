"""Handle inbound Telegram messages to the health coach."""

import asyncio
from logging import getLogger

from app.agent.loop import generate_reply
from app.agent.mcp_client import open_mcp_client
from app.briefing import run_for_date, yesterday_local
from app.channels.telegram import IncomingMessage, send_alert, send_chat_action, send_reply
from app.storage import db

logger = getLogger(__name__)

HELP_TEXT = (
    "<b>Open Wearables coach</b>\n"
    "\n"
    "I can pull your wearable data and answer questions about sleep, workouts, and activity.\n"
    "\n"
    "Commands:\n"
    "- /brief — send yesterday's daily briefing now\n"
    "- /clear — forget this chat's recent history\n"
    "- /help — this message\n"
    "\n"
    'Or just ask, e.g. "How did I sleep this week?"'
)

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
            "Cleared. Ask me anything about your health data.",
            reply_to_message_id=message.message_id,
        )
        return
    if text == "/brief":
        async with _busy:
            await run_for_date(yesterday_local(), force=True)
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
