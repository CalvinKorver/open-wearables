from datetime import date

from app.agent.prompts import (
    ALLOWED_TOOLS,
    CHAT_ALLOWED_TOOLS,
    CHAT_SYSTEM_PROMPT,
    MANAGED_SYSTEM_PROMPT,
    MEMORY_ATTACHMENT_INSTRUCTIONS,
    SYSTEM_PROMPT,
    turn_context,
    user_prompt,
)


def test_user_prompt_contains_iso_date_and_user_id():
    text = user_prompt(date(2026, 5, 7), "abc-123")
    assert "2026-05-07" in text
    assert "2026-05-08" in text  # sleep wake date is the following morning
    assert "abc-123" in text
    assert "start_date" in text
    assert "end_date" in text
    assert "get_sleep_summary" in text
    assert "User local timezone (IANA):" in text
    assert "America/Los_Angeles" in text


def test_user_prompt_uses_same_date_for_start_and_end():
    text = user_prompt(date(2026, 1, 1), "u")
    occurrences = text.count("2026-01-01")
    assert occurrences >= 2


def test_allowed_tools_subset():
    assert frozenset({"get_workout_events", "get_sleep_summary"}) == ALLOWED_TOOLS


def test_chat_allowed_tools_include_activity_and_timeseries():
    assert ALLOWED_TOOLS < CHAT_ALLOWED_TOOLS
    assert "get_activity_summary" in CHAT_ALLOWED_TOOLS
    assert "get_timeseries" in CHAT_ALLOWED_TOOLS
    assert "get_users" not in CHAT_ALLOWED_TOOLS


def test_system_prompt_mentions_required_constraints():
    for token in ["HTML", "user_id", "yesterday", "Telegram", "<b>", "start_local", "IANA", "sleep"]:
        assert token in SYSTEM_PROMPT


def test_chat_system_prompt_mentions_conversation_constraints():
    for token in ["HTML", "user_id", "get_activity_summary", "get_timeseries", "Telegram", "<b>"]:
        assert token in CHAT_SYSTEM_PROMPT


def test_managed_prompt_defines_confirmed_structured_memory():
    for token in ["athlete-profile.json", "goals", "injuries", "preferences", "confirmation", "/memory", "/forget"]:
        assert token in MANAGED_SYSTEM_PROMPT
    assert "sole durable memory" in MEMORY_ATTACHMENT_INSTRUCTIONS


def test_turn_context_has_user_timezone_and_source():
    context = turn_context(update_id=12, message_id=34)
    assert "00000000-0000-0000-0000-000000000001" in context
    assert "America/Los_Angeles" in context
    assert "telegram:12:34" in context
