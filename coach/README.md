# Open Wearables Coach

Personal AI health coach over Telegram. It sends a daily briefing, answers follow-up questions using Open Wearables data, and remembers confirmed goals, injuries, and preferences.

The coach is a small Telegram relay. It runs APScheduler, long-polls Telegram `getUpdates`, and sends turns to one persistent [Claude Managed Agents](../docs/mcp-server/managed-agents-remote.mdx) session. The managed agent calls the remote Open Wearables MCP and stores a structured athlete profile in a native Anthropic memory store.

This is the **Telegram health agent** for a single user. Chat history and durable memory stay in Anthropic; the relay keeps no local transcript.

## How it works

```text
Telegram (you)
   |  getUpdates long-poll (inbound) + sendMessage (outbound)
   v
coach/
   |-- APScheduler daily briefing
   |-- chat replies (/brief, /memory, /forget, /clear, free text)
   v
Claude Managed Agents session ---> native memory store
   v
Open Wearables MCP (HTTPS) ---> OW backend REST API
```

SQLite state (`coach.db`):

- `briefing_run` — one row per local date so a briefing is not sent twice
- `telegram_state` — `getUpdates` offset so restarts skip already-seen messages
- `managed_session_state` — active Anthropic session ID

The Managed Agents session contains the chat. Its store contains one `athlete-profile.json` document with confirmed goals, injuries/constraints, and preferences.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) `>= 0.9.17`
- A deployed Open Wearables backend and bearer-authenticated HTTPS MCP with connected wearable data
- An Anthropic API key
- A Claude Managed Agent, environment, MCP vault, and dedicated native memory store
- A Telegram bot (steps below)

## Telegram bot setup (one time)

1. In Telegram, open a chat with `@BotFather` and send `/newbot`. Follow the prompts to name your bot. BotFather replies with an HTTP API token like `123456:ABC-...`. Put it in `TELEGRAM_BOT_TOKEN`.
2. In Telegram, open your new bot and send it any message (for example, `/start`).
3. From a terminal, fetch the chat id:

   ```bash
   curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates" | jq '.result[].message.chat.id'
   ```

   Put that id in `TELEGRAM_CHAT_ID`. Only that chat is answered; other senders are ignored.

4. Disable privacy mode if you want the bot in a group (optional): BotFather → `/setprivacy` → Disable. For a 1:1 DM this is unnecessary.

At startup the coach calls `getMe` to verify the token, then long-polls `getUpdates`. No public webhook URL is required.

Once it is running, DM the bot:

- `/help` — commands
- `/brief` — send yesterday's briefing now
- `/memory` — inspect durable memory
- `/forget <description>` — remove a durable memory
- `/clear` — start a fresh chat while retaining durable memory
- `/forget all` then `/forget all confirm` — delete live memories and coach sessions
- or ask in plain language, e.g. "How did I sleep this week?"

## Configure

```bash
cp config/.env.example config/.env
```

Edit `config/.env` and fill in the required values. See the comments in the file for every variable.

Required:

- `OW_USER_ID`
- `ANTHROPIC_API_KEY`
- `MANAGED_AGENT_ID`
- `MANAGED_ENVIRONMENT_ID`
- `MANAGED_VAULT_IDS`
- `MANAGED_MEMORY_STORE_ID`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Optional with defaults:

- `ANTHROPIC_API_URL` (default `https://api.anthropic.com`)
- `MANAGED_AGENT_TIMEOUT_SECONDS` (default `300`)
- `BRIEFING_TIMEZONE` (default `America/Los_Angeles`)
- `BRIEFING_TIME` (default `11:00`)
- `COACH_DB_PATH` (default `./coach.db`; set to `/data/coach.db` in the container)
- `LOG_LEVEL` (default `INFO`)

## Run

### Local

```bash
cd coach
uv sync
uv run start
```

The scheduler logs the next fire time at startup and then waits.

### Docker (alongside Open Wearables)

The coach is wired into the project's `docker-compose.yml` as a `coach` service.

```bash
# from the repo root
docker compose up -d coach
docker compose logs -f coach
```

The coach container is only the Telegram relay. The managed agent connects to your separately deployed HTTPS MCP. SQLite operational state lives in the `coach_data` volume.

## Run a briefing on demand

For testing, debugging, or backfilling a missed day, use the wrapper (finds `uv` and `--force`s by default):

```bash
# from the repo root — yesterday in BRIEFING_TIMEZONE
./coach/scripts/send-test-brief

# a specific date
./coach/scripts/send-test-brief --date 2026-08-30

# skip re-send if that date already went out
./coach/scripts/send-test-brief --date 2026-08-30 --no-force
```

Or call the CLI directly from `coach/`:

```bash
# brief yesterday in BRIEFING_TIMEZONE
uv run brief

# brief a specific date
uv run brief --date 2026-05-07

# re-run even if a briefing was already sent for that date
uv run brief --date 2026-05-07 --force
```

In Docker:

```bash
docker compose exec coach uv run --no-sync brief --date 2026-05-07 --force
```

## Tests

```bash
cd coach
uv sync --group dev
uv run pytest -v
```

The tests do not hit Anthropic, Telegram, or the Open Wearables API. They cover memory policy, briefing idempotency, Telegram handling, session persistence, stream-first Managed Agents events, permission pauses, and lifecycle recovery.

## Code quality

```bash
cd coach
uv run ruff check . --fix
uv run ruff format .
```

## Troubleshooting

### "Missing required environment variables"

The coach checks for required env vars on startup. The error message lists which ones are missing. Verify they are set in `coach/config/.env` (or the container's environment).

### "Managed Agent requested tool approval"

The relay intentionally does not approve unknown tools. Configure the Open Wearables MCP toolset with `default_config.enabled=false`; enable only the read-only health tools and set them to `permission_policy: {"type": "always_allow"}`.

### Memory is not retained after `/clear`

Verify `MANAGED_MEMORY_STORE_ID` stays the same and that the agent has its built-in `read` and `write` tools enabled. `/clear` archives only the chat session.

### Telegram returns 400 "can't parse entities"

The briefing is sent with `parse_mode=HTML`. If the model emits invalid HTML (e.g. an unbalanced `<b>` tag), Telegram returns 400. The coach automatically strips tags and re-sends as plain text, so the briefing still arrives. You'll see a `WARNING` in the logs noting the fallback. If the plain-text retry also fails, the briefing run is marked failed and a plain-text alert is sent to the same chat.

### The coach was down at 11 AM and is now running at 12:30 PM

APScheduler's `misfire_grace_time` is 60 minutes. If the coach starts up within an hour of the missed trigger, the briefing fires immediately. If you missed the window, run `uv run brief` manually.

### "uv: command not found" on macOS

`uv` is installed at `~/.local/bin/uv`. Use that path, or open a new terminal so `~/.zprofile` puts it on PATH:

```bash
~/.local/bin/uv run brief --date 2026-08-30 --force
```

### "uv: command not found" inside the container at startup

The image installs `uv` from the official upstream image. Rebuild with `docker compose build coach` if your image is stale.

### Bot does not answer DMs

- Confirm the process logged `Telegram bot connected username=...` at startup (`getMe` succeeded).
- Confirm `TELEGRAM_CHAT_ID` matches the chat you are messaging (the coach ignores every other chat).
- After a deploy, pending DMs sent while the coach was down are drained and not answered, so send a new message.
- Watch logs for `Telegram getUpdates failed` — token errors, network, or Telegram 429s back off and retry.

### Replies ignore conversation context

Verify the active ID exists in `managed_session_state`. Send `/clear` to intentionally archive it and create a clean session on the next message.

## What's next

- Multiple users and channels (Twilio SMS, WhatsApp, etc.)
- Per-user Managed Agents sessions and memory stores

## License

MIT - see the main project LICENSE.
