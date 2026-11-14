"""Scrape every source in a config file and send it to the API.

    python -m rec_scrapers.run --config sources.json --browser-channel msedge

The config lists facilities (with the venue codes that belong to them) and the
sources to scrape. A source is a Connect2 counts page or the Browse Events
page; the API works out which, so adding a facility or a link is a config
change, not a code change. See sources.example.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from rec_normalizers import ParseError, detect_page_type

from .client import PostError, post_ingest, put_facility
from .connect2 import DEFAULT_TIMEZONE, ScrapeError, fetch_rendered_html
from .events import fetch_rendered_events_days, fetch_rendered_events_html
from .pdf import download_pdf, pdf_to_content

SOURCE_TYPES = ("connect2_counts", "events", "pool_schedule")


class ConfigError(ValueError):
    pass


def load_config(path: Path) -> dict:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc

    base = path.parent
    facilities, sources, seen = [], [], set()

    def add_source(raw: dict, facility_id: str | None):
        sid = raw.get("id")
        if not sid:
            raise ConfigError("every source needs an id")
        if sid in seen:
            raise ConfigError(f"duplicate source id {sid!r}")
        seen.add(sid)
        if raw.get("type") not in SOURCE_TYPES:
            raise ConfigError(f"source {sid!r}: type must be one of {', '.join(SOURCE_TYPES)}")
        if not any(raw.get(k) for k in ("url", "url_env", "html_file", "pdf_file")):
            raise ConfigError(f"source {sid!r}: give a url, url_env, html_file or pdf_file")
        if "days" in raw and (not isinstance(raw["days"], int) or isinstance(raw["days"], bool)
                              or not 1 <= raw["days"] <= 31):
            raise ConfigError(f"source {sid!r}: days must be a whole number from 1 to 31")
        if raw["type"] == "pool_schedule" and raw.get("html_file"):
            raise ConfigError(f"source {sid!r}: a pool calendar is a PDF; use pdf_file or url")
        if raw["type"] == "connect2_counts" and not facility_id:
            raise ConfigError(f"source {sid!r}: a counts page must sit under a facility")
        sources.append({**raw, "facility_id": facility_id, "_base": base})

    for fac in config.get("facilities", []):
        if not fac.get("id") or not fac.get("name"):
            raise ConfigError("every facility needs an id and a name")
        facilities.append(
            {"id": fac["id"], "name": fac["name"], "type": fac.get("type", "other"),
             "venues": fac.get("venues", [])}
        )
        for raw in fac.get("sources", []):
            add_source(raw, fac["id"])
    for raw in config.get("sources", []):
        add_source(raw, None)

    return {"api": config.get("api", "http://localhost:8000"),
            "timezone": config.get("timezone", DEFAULT_TIMEZONE),
            "facilities": facilities, "sources": sources}


def _get_html(source: dict, args, timezone: str) -> str:
    if source["type"] == "pool_schedule":
        if source.get("pdf_file"):
            path = source["_base"] / source["pdf_file"]
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise ScrapeError(f"cannot read the pool calendar PDF at {path}: {exc.strerror}") from exc
        else:
            data = download_pdf(source.get("url") or os.environ.get(source.get("url_env") or "", ""))
        return pdf_to_content(data)
    if source.get("html_file"):
        return (source["_base"] / source["html_file"]).read_text(encoding="utf-8")
    url = source.get("url")
    if source.get("url_env"):
        url = os.environ.get(source["url_env"])
        if not url:
            raise ScrapeError(f"environment variable {source['url_env']} is not set")
    fetch = fetch_rendered_html if source["type"] == "connect2_counts" else fetch_rendered_events_html
    return fetch(
        url, timezone_id=timezone, timeout_ms=args.timeout_ms,
        channel=args.browser_channel, no_sandbox=args.no_sandbox,
    )


DEFAULT_DAYS = 7


def _get_pages(source: dict, args, timezone: str) -> tuple[list[tuple[str | None, str]], str | None]:
    """(day, content) pairs to send. A live events page gives one per day, tagged with the
    day the page itself showed; anything else gives one, tagged with --date if given."""
    live_events = (
        source["type"] == "events" and not source.get("html_file")
    )
    if not live_events:
        return [(args.date, _get_html(source, args, timezone))], None
    url = source.get("url")
    if source.get("url_env"):
        url = os.environ.get(source["url_env"])
        if not url:
            raise ScrapeError(f"environment variable {source['url_env']} is not set")
    days = args.days or source.get("days") or DEFAULT_DAYS
    if args.date:  # one named day: read just the page that is showing
        days = 1
    got = fetch_rendered_events_days(
        url, days=days, timezone_id=timezone, timeout_ms=args.timeout_ms,
        channel=args.browser_channel, no_sandbox=args.no_sandbox,
    )
    return [(args.date or d.isoformat(), html) for d, html in got.pages], got.note


def _save_empty_page(source_id: str, html: str) -> str:
    """An events page that yields nothing: keep what the browser saw so it can be inspected."""
    from pathlib import Path

    path = Path(f"debug-{source_id}.html")
    try:
        path.write_text(html, encoding="utf-8")
        where = f"saved the page to {path.resolve()}"
    except OSError:
        where = "could not save the page"
    return (
        f"0 events found; {where} ({len(html)} characters, "
        f"{html.count('<tr')} table rows, 'No data' shown: {'dx-datagrid-nodata' in html})"
    )


def run(config: dict, args) -> list[dict]:
    api, timezone = args.api or config["api"], config["timezone"]
    results: list[dict] = []

    # Make sure every facility exists, with its venues, before sending data.
    for fac in config["facilities"]:
        try:
            put_facility(api, fac["id"], name=fac["name"], type=fac["type"], venues=fac["venues"])
        except PostError as exc:
            results.append({"source": f"facility:{fac['id']}", "ok": False, "error": str(exc)})

    for source in config["sources"]:
        if args.only and source["id"] not in args.only:
            continue
        entry = {"source": source["id"], "type": source["type"]}
        try:
            pages, note = _get_pages(source, args, timezone)
            responses = []
            for day, html in pages:
                found = detect_page_type(html)
                if found != source["type"]:
                    raise ParseError(
                        f"expected a {source['type']} page but got {found or 'something else'}"
                    )
                responses.append(post_ingest(
                    api, source_id=source["id"], content=html,
                    facility_id=source["facility_id"], event_date=day,
                    source_timezone=timezone,
                ))
            entry["response"] = responses[0]
            if len(responses) > 1:  # one line per day: the day, how many events, and where they went
                entry["days"] = [
                    {"date": r["event_date"], "events": r["events"], "by_facility": r["by_facility"]}
                    for r in responses
                ]
            entry["ok"] = True
            if note:
                entry["warning"] = note
            if source["type"] == "events" and not any(r.get("events") for r in responses):
                entry["warning"] = "; ".join(filter(None, [entry.get("warning"), _save_empty_page(source["id"], pages[0][1])]))
        except (ScrapeError, ParseError, PostError, OSError) as exc:
            entry.update(ok=False, error=str(exc))
        results.append(entry)
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rec_scrapers.run", description=__doc__.split("\n\n")[0])
    p.add_argument("--config", type=Path, required=True, help="sources.json")
    p.add_argument("--only", action="append", metavar="SOURCE_ID", help="run just this source (repeatable)")
    p.add_argument("--api", help="override the API address in the config")
    p.add_argument("--date", help="events pages: read only the day the page opens on and file it under this day, YYYY-MM-DD")
    p.add_argument("--days", type=int, help=f"events pages: how many days to read, starting today (default: the source's `days`, else {DEFAULT_DAYS})")
    p.add_argument("--timeout-ms", type=int, default=30_000)
    p.add_argument("--browser-channel", default=None, help='for example "msedge" or "chrome"')
    p.add_argument("--no-sandbox", action="store_true")
    args = p.parse_args(argv)

    if args.days is not None and not 1 <= args.days <= 31:
        print("error: --days must be a whole number from 1 to 31", file=sys.stderr)
        return 2
    if args.date:
        try:
            date.fromisoformat(args.date)
        except ValueError:
            print(f"error: --date must look like 2026-11-12, got {args.date!r}", file=sys.stderr)
            return 2
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    unknown = set(args.only or []) - {s["id"] for s in config["sources"]}
    if unknown:
        print(f"error: no such source: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    results = run(config, args)
    json.dump({"results": results}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    failed = [r for r in results if not r["ok"]]
    if failed:
        print(f"{len(failed)} of {len(results)} failed", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())