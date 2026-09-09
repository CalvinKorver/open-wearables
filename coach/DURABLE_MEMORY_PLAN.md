# Plan: Durable goals and facts (commands-only)

**Status:** awaiting approval  
**Scope:** Telegram coach (`coach/`) long-lived memory via explicit commands only. No auto-extraction from free-text chat.

## Decision

Short-term chat history (`conversation_turn`, last 20 turns) stays as-is. Durable goals and facts live in a separate SQLite store that survives `/clear` and process restarts. Users add/list/forget memory only through Telegram slash commands.

## Data model

Extend [`app/storage/db.py`](app/storage/db.py) with:

```text
memory_item
  id          INTEGER PK autoincrement
  kind        TEXT NOT NULL   -- "goal" | "fact"
  content     TEXT NOT NULL
  created_at  DATETIME NOT NULL
  updated_at  DATETIME NOT NULL
```

Helpers: `list_memory`, `add_memory`, `delete_memory`, `clear_memory`.

Limits:

- 500 characters per item
- 20 goals and 40 facts max (reject adds with a clear Telegram error when full)
- Schema created via existing `Base.metadata.create_all` on startup

`/clear` continues to wipe only `conversation_turn`.

## Telegram commands

Route in [`app/chat.py`](app/chat.py) before the free-text agent path. Update `HELP_TEXT`.

| Command | Behavior |
|---------|----------|
| `/goal <text>` | Add a goal; reply with id + confirmation |
| `/fact <text>` | Add a fact; reply with id + confirmation |
| `/goals` | List goals as `#id: content` |
| `/facts` | List facts |
| `/memory` | Goals then facts (or empty-state message) |
| `/forget <id>` | Delete by numeric id |
| `/forget goals` / `/forget facts` / `/forget all` | Bulk clear; reply with count deleted |

Empty `/goal` or `/fact` returns usage help. These commands do **not** append to `conversation_turn`.

## Prompt injection

In [`app/agent/prompts.py`](app/agent/prompts.py) and [`app/agent/loop.py`](app/agent/loop.py):

1. Format a durable-profile block when any items exist, for example:

```text
Durable profile (user-set; treat as ground truth unless they update it):
Goals:
- (#3) Race Ironman 70.3 on 2026-10-12
Facts:
- (#7) Prefer morning workouts
```

2. Append that block to chat and briefing system prompts.

3. Prompt rules:

- Personalize advice and briefing focus using listed goals/facts
- Never invent goals/facts not listed
- If asked to remember something, tell the user to use `/goal` or `/fact`

## Docs and tests

- Update [`README.md`](README.md) and [`../docs/coach.mdx`](../docs/coach.mdx) command tables
- Tests: storage CRUD + caps; command routing; `/clear` does not wipe memory; prompt includes memory when present

## Out of scope

- Auto-extract from chat
- Soft-delete / forgotten-item history
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
