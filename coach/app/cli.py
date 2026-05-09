"""One-shot CLI for manual briefings.

Usage:
    uv run brief                        # brief yesterday in BRIEFING_TIMEZONE
    uv run brief --date 2026-05-07      # brief a specific date
    uv run brief --date 2026-05-07 -f   # re-brief even if already sent
"""

import argparse
import asyncio
import logging
import sys
from datetime import date

from app.briefing import run_for_date, yesterday_local
from app.config import settings


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"--date must be YYYY-MM-DD, got: {value}") from e


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brief", description="Run a single coach briefing on demand.")
    parser.add_argument(
        "--date",
        "-d",
        type=_parse_date,
        default=None,
        help="Date to brief in YYYY-MM-DD (defaults to yesterday in BRIEFING_TIMEZONE).",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Re-run even if a briefing was already sent for that date.",
    )
    return parser


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    args = _build_parser().parse_args()

    missing = settings.required_missing()
    if missing:
        sys.stderr.write(
            "Missing required environment variables: " + ", ".join(missing) + "\nSee coach/config/.env.example.\n"
        )
        sys.exit(2)

    target = args.date or yesterday_local()
    asyncio.run(run_for_date(target, force=args.force))


if __name__ == "__main__":
    main()
