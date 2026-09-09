# Plan: Durable goals and facts (commands-only)

**Status:** awaiting approval  
**Scope:** Telegram coach (`coach/`) long-lived memory via explicit commands only. No auto-extraction from free-text chat.

## Decision

Short-term chat history (`conversation_turn`, last 20 turns) stays as-is. Durable goals and facts live in a separate SQLite store that survives `/clear` and process restarts. Users add/list/forget memory only through Telegram slash commands.

## Data model

Extend [`app/storage/db.py`](app/storage/db.py):

```python
class MemoryKind(StrEnum):
    GOAL = "goal"
    FACT = "fact"

class MemoryItem(Base):
    __tablename__ = "memory_item"
    id: Mapped[int]  # PK autoincrement
    kind: Mapped[str]  # MemoryKind value
    content: Mapped[str]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

MAX_MEMORY_CONTENT_CHARS = 500
MAX_GOALS = 20
MAX_FACTS = 40
```

API:

| Function | Behavior |
|----------|----------|
| `list_memory(kind: MemoryKind \| None = None)` | Chronological list |
| `add_memory(kind, content)` | Trim; raise `ValueError` if empty; raise `MemoryFullError` / `MemoryTooLongError` on caps |
| `delete_memory(id: int) -> bool` | False if missing |
| `clear_memory(kind: MemoryKind \| None = None) -> int` | Rows deleted |
| `format_memory_block() -> str` | Empty string if no items; else prompt-ready block |

Schema via existing `init_db()` → `create_all` (SQLite adds new table safely).

`/clear` continues to wipe only `conversation_turn`.

## Telegram commands

Route in [`app/chat.py`](app/chat.py) **before** the free-text agent path (same style as `/help` / `/clear`). Update `HELP_TEXT`.

Parsing after `normalize_command`:

| Input | Result |
|-------|--------|
| `/goal Race 70.3 in October` | Add goal; reply `Saved goal #12: Race 70.3 in October` |
| `/goal` (no text) | Usage: `Usage: /goal <text>` |
| `/fact Prefer morning workouts` | Add fact; reply with id |
| `/fact` | Usage help |
| `/goals` | `Goals:\n- #12: …` or `No goals saved.` |
| `/facts` | Same for facts |
| `/memory` | Goals section then facts section |
| `/forget 12` | `Forgot #12.` or `No memory item #12.` |
| `/forget goals` / `/forget facts` / `/forget all` | `Forgot N goal(s).` etc. |
| `/forget` / bad args | Usage for `/forget` |

Command replies do **not** append to `conversation_turn`. Cap/validation errors become plain Telegram replies (no stack traces).

## Prompt injection

Touch [`app/agent/prompts.py`](app/agent/prompts.py) and [`app/agent/loop.py`](app/agent/loop.py):

1. `format_memory_block()` output example when non-empty:

```text
Durable profile (user-set; treat as ground truth unless they update it):
Goals:
- (#12) Race 70.3 in October
Facts:
- (#3) Prefer morning workouts
```

2. Append to:
   - `_chat_system_prompt()` always (omit block if empty)
   - briefing path in `generate_briefing` / `_run_agent` system string so morning focus respects goals

3. Add to `SYSTEM_PROMPT` / `CHAT_SYSTEM_PROMPT` rules:
   - Personalize using listed goals/facts
   - Never invent unlisted goals/facts
   - If asked to remember something, tell the user to use `/goal` or `/fact`

## Files to change (implementation)

| File | Change |
|------|--------|
| `coach/app/storage/db.py` | Model + CRUD + caps + `format_memory_block` |
| `coach/app/chat.py` | Command routing + HELP_TEXT |
| `coach/app/agent/prompts.py` | Memory-aware prompt rules |
| `coach/app/agent/loop.py` | Inject memory into chat + briefing system prompts |
| `coach/tests/test_storage.py` | Memory CRUD/caps; clear conversation ≠ clear memory |
| `coach/tests/test_chat.py` | Command routing + help text |
| `coach/tests/test_loop.py` or new `test_memory_prompt.py` | System prompt includes/omits block |
| `coach/README.md` | Commands + note `/clear` vs durable memory |
| `docs/coach.mdx` | Same |
| `coach/DURABLE_MEMORY_PLAN.md` | Remove after implementation lands (or replace with short “how memory works” note) |

## Out of scope

- Auto-extract from chat
- Soft-delete / forgotten-item history
- Edit-in-place (`/goal` always adds; use `/forget` then re-add)
- Multi-user memory
- Managed Agents relay

## Flow

```text
Telegram DM
  |-- /goal /fact /forget /memory --> memory_item (SQLite)
  |-- free text ---------------------> conversation_turn + agent loop
                                              ^
                                              |
                                   durable profile in system prompt
```

## Approval

Reply on this PR or in chat with **Approve**, **Approve with changes: …**, or **Revise: …**.
After approval, implementation replaces this proposal with the feature above.
