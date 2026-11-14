"""One command: load a Connect2 counts page, parse it, print the activity JSON.

Examples:
    export CONNECT2_URL='https://www.connect2mycloud.com/Widgets/Data/locationCount?...'
    python -m rec_scrapers --url-env CONNECT2_URL

    python -m rec_scrapers --html-file saved_page.html      # no browser needed

    # scrape and store in one step
    python -m rec_scrapers --url-env CONNECT2_URL --post-to http://localhost:8000 \\
        --facility-id wooden-center
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from rec_normalizers import ParseError, parse_connect2_counts

from .client import PostError, post_activity
from .connect2 import DEFAULT_TIMEZONE, ScrapeError, fetch_rendered_html, redact_url


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rec_scrapers",
        description="Scrape a Connect2Concepts live counts page into activity JSON.",
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="live counts page URL (the query string holds a key)")
    src.add_argument(
        "--url-env",
        metavar="NAME",
        help="read the URL from this environment variable (keeps the key out of shell history)",
    )
    src.add_argument("--html-file", type=Path, help="parse an already-rendered saved page")
    p.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="zone the page prints times in")
    p.add_argument("--stale-after-minutes", type=int, default=30)
    p.add_argument("--timeout-ms", type=int, default=20_000)
    p.add_argument("--browser-channel", default=None, help='for example "chrome"')
    p.add_argument("--no-sandbox", action="store_true", help="needed when running as root in a container")
    p.add_argument("--save-html", type=Path, help="also write the rendered HTML here (for debugging or reprocessing)")
    p.add_argument(
        "--post-to",
        metavar="BASE_URL",
        help="send the page to this API instead of printing it, for example http://localhost:8000",
    )
    p.add_argument("--facility-id", help="the facility's id in the API (required with --post-to)")
    p.add_argument("--source-id", default="connect2", help="label for where the page came from")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.post_to and not args.facility_id:
        parser.error("--facility-id is required with --post-to")

    try:
        if args.html_file:
            html = args.html_file.read_text(encoding="utf-8")
            source = str(args.html_file)
        else:
            url = args.url
            if args.url_env:
                url = os.environ.get(args.url_env)
                if not url:
                    raise ScrapeError(f"environment variable {args.url_env} is not set")
            html = fetch_rendered_html(
                url,
                timezone_id=args.timezone,
                timeout_ms=args.timeout_ms,
                channel=args.browser_channel,
                no_sandbox=args.no_sandbox,
            )
            source = redact_url(url)

        if args.save_html:
            args.save_html.write_text(html, encoding="utf-8")

        if args.post_to:
            # The API parses and validates the page itself, so this is the one
            # place that decides whether it is good.
            result = post_activity(
                args.post_to,
                facility_id=args.facility_id,
                source_id=args.source_id,
                content=html,
                source_timezone=args.timezone,
            )
            json.dump(
                {"source": source, "posted_to": args.post_to.rstrip("/"), "api_response": result},
                sys.stdout,
                indent=2,
            )
            sys.stdout.write("\n")
            return 0

        counts = parse_connect2_counts(html, source_tz=args.timezone)
    except (ScrapeError, ParseError, PostError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    output = {
        "source": source,
        "fetched_at": now.isoformat().replace("+00:00", "Z"),
        "facility_name": counts.facility_name,
        "official": counts.to_official(now=now, stale_after_minutes=args.stale_after_minutes),
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
