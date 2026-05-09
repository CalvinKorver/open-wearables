# Open Wearables Coach

Personal AI coach that sends a daily Telegram briefing summarizing yesterday's workouts and health metrics from Open Wearables.

The coach is a small standalone Python service. It runs APScheduler in-process, spawns the Open Wearables MCP server (see [`../mcp/`](../mcp/)) as a stdio subprocess to fetch data, asks Claude to summarize, and posts the result to a Telegram chat.

## How it works

```text
APScheduler (cron in your TZ)
        |
        v
briefing.run_daily()
        |
        v
Claude agent loop
        |
        v
fastmcp.Client (stdio) ---> Open Wearables MCP ---> OW backend REST API
        |
        v
Telegram Bot API ---> your phone
```

State persisted to a small SQLite file (`briefing_run` table) so the same date can never be sent twice.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) `>= 0.9.17`
- A running Open Wearables backend (locally via `docker compose up -d` or a deployed instance) with at least one connected provider syncing data
- An Open Wearables API key for your user (Dashboard -> Settings -> Credentials -> Create API Key)
- An Anthropic API key
- A Telegram bot (steps below)

## Telegram bot setup (one time)

1. In Telegram, open a chat with `@BotFather` and send `/newbot`. Follow the prompts to name your bot. BotFather replies with an HTTP API token like `123456:ABC-...`. Put it in `TELEGRAM_BOT_TOKEN`.
2. In Telegram, open your new bot and send it any message (for example, `/start`).
3. From a terminal, fetch the chat id:

   ```bash
   curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates" | jq '.result[].message.chat.id'
   ```

   Put that id in `TELEGRAM_CHAT_ID`.

That is the only manual step. The coach uses outbound `sendMessage` only; no public webhook URL is needed in v1.

## Configure

```bash
cp config/.env.example config/.env
```

Edit `config/.env` and fill in the required values. See the comments in the file for every variable.

Required:

- `OPEN_WEARABLES_API_URL`
- `OPEN_WEARABLES_API_KEY`
- `OW_USER_ID`
- `ANTHROPIC_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Optional with defaults:

- `OW_MCP_DIR` (default `/opt/mcp` in the container, set to `../mcp` for local dev)
- `ANTHROPIC_MODEL` (default `claude-sonnet-4-5`)
- `BRIEFING_TIMEZONE` (default `America/Los_Angeles`)
- `BRIEFING_TIME` (default `07:00`)
- `COACH_DB_PATH` (default `./coach.db`; set to `/data/coach.db` in the container)
- `LOG_LEVEL` (default `INFO`)

## Run

### Local

```bash
cd coach
uv sync
OW_MCP_DIR=../mcp uv run start
```

The scheduler logs the next fire time at startup and then waits.

### Docker (alongside Open Wearables)

The coach is wired into the project's `docker-compose.yml` as a `coach` service.

```bash
# from the repo root
docker compose up -d coach
docker compose logs -f coach
```

The container bundles both `coach/` and `mcp/`, so it can spawn the MCP server as a stdio subprocess without any additional setup. SQLite state lives in the `coach_data` volume.

## Run a briefing on demand

For testing, debugging, or backfilling a missed day:

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
docker compose exec coach uv run --no-sync brief --date 2026-05-07
```

## Tests

```bash
cd coach
uv sync --group dev
uv run pytest -v
```

The tests do not hit Anthropic, Telegram, or the Open Wearables API; they cover prompt building, idempotency, MarkdownV2 escaping, and the agent loop's tool dispatch.

## Code quality

```bash
cd coach
uv run ruff check . --fix
uv run ruff format .
```

## Troubleshooting

### "Missing required environment variables"

The coach checks for required env vars on startup. The error message lists which ones are missing. Verify they are set in `coach/config/.env` (or the container's environment).

### "OPEN_WEARABLES_API_KEY is not configured" in the MCP subprocess logs

The MCP server reads its own env from the variables the coach passes in. Make sure `OPEN_WEARABLES_API_KEY` is set in the coach's environment; the coach forwards it explicitly to the subprocess.

### Telegram returns 400 "can't parse entities"

The briefing is sent with `parse_mode=HTML`. If the model emits invalid HTML (e.g. an unbalanced `<b>` tag), Telegram returns 400. The coach automatically strips tags and re-sends as plain text, so the briefing still arrives. You'll see a `WARNING` in the logs noting the fallback. If the plain-text retry also fails, the briefing run is marked failed and a plain-text alert is sent to the same chat.

### The coach was down at 7 AM and is now running at 8:30 AM

APScheduler's `misfire_grace_time` is 60 minutes. If the coach starts up within an hour of the missed trigger, the briefing fires immediately. If you missed the window, run `uv run brief` manually.

### "uv: command not found" inside the container at startup

The image installs `uv` from the official upstream image. Rebuild with `docker compose build coach` if your image is stale.

## What's next (v2)

- Two-way replies: inbound webhook + multi-turn conversation memory
- Long-lived facts and goals to personalize the briefings
- Multiple users and channels (Twilio SMS, WhatsApp, etc.)
- Switching the OW MCP transport from stdio to HTTP/SSE if the coach grows beyond a single user

## License

MIT - see the main project LICENSE.
