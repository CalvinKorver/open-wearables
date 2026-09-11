"""Handle inbound Telegram messages to the health coach."""

import asyncio
from logging import getLogger

from app.agent.managed_client import clear_session, forget_all_data, run_turn
from app.briefing import run_for_date, yesterday_local
from app.channels.telegram import IncomingMessage, send_alert, send_chat_action, send_reply

logger = getLogger(__name__)

HELP_TEXT = (
    "<b>Open Wearables coach</b>\n"
    "\n"
    "I can pull your wearable data and answer questions about sleep, workouts, and activity.\n"
    "\n"
    "Commands:\n"
    "- /brief — send yesterday's daily briefing now\n"
    "- /memory — show durable goals, injuries, and preferences\n"
    "- /forget &lt;description&gt; — remove a stored memory\n"
    "- /clear — start a fresh chat while keeping durable memory\n"
    "- /forget all — begin deleting all memory and chat history\n"
    "- /help — this message\n"
    "\n"
    'Or just ask, e.g. "How did I sleep this week?"'
)

# A Managed Agents session processes one ordered turn at a time.
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
        await clear_session()
        await send_reply(
            "Started a fresh chat. Your durable goals, injuries, and preferences are still available.",
            reply_to_message_id=message.message_id,
        )
        return
    if text == "/forget all":
        await send_reply(
            "This deletes all durable memories and every Managed Agents chat for this Telegram account. "
            "Send <code>/forget all confirm</code> to continue.",
            reply_to_message_id=message.message_id,
        )
        return
    if text == "/forget all confirm":
        async with _busy:
            await forget_all_data()
        await send_reply(
            "Deleted all live durable memories and Managed Agents chat sessions. "
            "Anthropic may retain memory versions for its documented retention window.",
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
        reply = await run_turn(
            text,
            update_id=message.update_id,
            message_id=message.message_id,
        )
    except Exception as e:
        logger.exception("Chat reply failed")
        await send_alert(f"Coach reply failed: {e}")
        return
    finally:
        stop_typing.set()
        await typing_task

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
