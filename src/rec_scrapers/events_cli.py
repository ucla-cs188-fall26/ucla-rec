"""Scrape the UCLA Rec Browse Events page into normalized events.

Examples:
    # from a saved, rendered page (no browser needed)
    python -m rec_scrapers.events_cli --html-file page.html --date 2026-11-12

    # live page, stored in the API
    python -m rec_scrapers.events_cli --browser-channel msedge --post-to http://localhost:8000

The page shows one day at a time and its rows carry no date, so --date must be
the day the page is showing (default: today in Los Angeles).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from rec_normalizers import ParseError, parse_vems_events

from .client import PostError, post_events
from .connect2 import DEFAULT_TIMEZONE, ScrapeError
from .events import EVENTS_URL, fetch_rendered_events_html


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rec_scrapers.events_cli",
        description="Scrape the UCLA Rec Browse Events grid.",
    )
    p.add_argument("--url", default=EVENTS_URL, help="events page (default: the UCLA Rec page)")
    p.add_argument("--html-file", type=Path, help="parse an already-rendered saved page")
    p.add_argument("--date", help="YYYY-MM-DD the page is showing (default: today in Los Angeles)")
    p.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    p.add_argument("--timeout-ms", type=int, default=30_000)
    p.add_argument("--browser-channel", default=None, help='for example "msedge" or "chrome"')
    p.add_argument("--no-sandbox", action="store_true")
    p.add_argument("--save-html", type=Path, help="also write the rendered HTML here")
    p.add_argument("--post-to", metavar="BASE_URL", help="send the page to this API")
    p.add_argument("--source-id", default="ucla-reserve-events")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        day = (
            date.fromisoformat(args.date)
            if args.date
            else datetime.now(ZoneInfo(args.timezone)).date()
        )
    except ValueError:
        print(f"error: --date must look like 2026-11-12, got {args.date!r}", file=sys.stderr)
        return 2

    try:
        if args.html_file:
            html = args.html_file.read_text(encoding="utf-8")
        else:
            html = fetch_rendered_events_html(
                args.url,
                timezone_id=args.timezone,
                timeout_ms=args.timeout_ms,
                channel=args.browser_channel,
                no_sandbox=args.no_sandbox,
            )
        if args.save_html:
            args.save_html.write_text(html, encoding="utf-8")

        if args.post_to:
            result = post_events(
                args.post_to,
                source_id=args.source_id,
                content=html,
                event_date=day.isoformat(),
                source_timezone=args.timezone,
            )
            json.dump({"posted_to": args.post_to.rstrip("/"), "api_response": result}, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0

        events = parse_vems_events(html, day, source_tz=args.timezone)
    except (ScrapeError, ParseError, PostError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    json.dump(
        {"event_date": day.isoformat(), "count": len(events),
         "events": [e.model_dump(mode="json") for e in events]},
        sys.stdout, indent=2,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
