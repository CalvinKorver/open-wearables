from datetime import date

from app.agent.prompts import ALLOWED_TOOLS, SYSTEM_PROMPT, user_prompt


def test_user_prompt_contains_iso_date_and_user_id():
    text = user_prompt(date(2026, 5, 7), "abc-123")
    assert "2026-05-07" in text
    assert "abc-123" in text
    assert "start_date" in text
    assert "end_date" in text
    assert "User local timezone (IANA):" in text
    assert "America/Los_Angeles" in text


def test_user_prompt_uses_same_date_for_start_and_end():
    text = user_prompt(date(2026, 1, 1), "u")
    occurrences = text.count("2026-01-01")
    assert occurrences >= 2


def test_allowed_tools_subset():
    assert ALLOWED_TOOLS == frozenset({"get_workout_events"})


def test_system_prompt_mentions_required_constraints():
    for token in ["HTML", "user_id", "yesterday", "Telegram", "<b>", "start_local", "IANA"]:
        assert token in SYSTEM_PROMPT
