"""Test fixtures for the coach service.

Sets a temp SQLite path via env BEFORE app modules are imported so the storage
module's module-level engine binds to a clean database for tests.
"""

import os
import tempfile
from pathlib import Path

_tmp_db = Path(tempfile.mkdtemp(prefix="coach-tests-")) / "coach.db"
os.environ.setdefault("COACH_DB_PATH", str(_tmp_db))
os.environ.setdefault("OPEN_WEARABLES_API_KEY", "test-key")
os.environ.setdefault("OW_USER_ID", "00000000-0000-0000-0000-000000000001")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "1234567")
os.environ.setdefault("BRIEFING_TIMEZONE", "America/Los_Angeles")
os.environ.setdefault("BRIEFING_TIME", "07:00")
