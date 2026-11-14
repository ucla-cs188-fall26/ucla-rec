"""Load the UCLA Rec Browse Events page in a headless browser.

The grid is filled in by JavaScript, so a plain download has no rows. This
returns the rendered HTML once the grid has either rows or its "No data" notice.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

from .connect2 import DEFAULT_TIMEZONE, ScrapeError, redact_url

EVENTS_URL = "https://reserve.recreation.ucla.edu/BrowseEvents.aspx"
# Rows appear, or the grid says there is nothing for the day.
# The page has two grids. The mobile one always holds a "No data" notice, so only
# the desktop grid (#eventResults) says anything about whether events have loaded.
ROWS_SELECTOR = "#eventResults tr.evenRows, #eventResults tr.oddRows"
NODATA_SELECTOR = "#eventResults .dx-datagrid-nodata:not(.dx-hidden)"
READY_SELECTOR = f"{ROWS_SELECTOR}, {NODATA_SELECTOR}"
# The page's daily view: the date it is showing, and the "next day" arrow.
LABEL_SELECTOR = "#dailyContainer span[aria-label]"
NEXT_SELECTOR = "#dailyContainer button:has(i.fa-chevron-right)"
_LABEL = re.compile(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})")


class EventsDays(NamedTuple):
    pages: list[tuple[date, str]]  # (the day the page showed, its rendered HTML)
    note: str | None  # set when fewer days than asked for could be read


def parse_page_date(text: str) -> date | None:
    """'Friday, November 13th 2026' -> 2026-11-13"""
    m = _LABEL.search(text or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m[1]} {m[2]} {m[3]}", "%B %d %Y").date()
    except ValueError:
        return None


def _new_page(browser, timezone_id: str):
    """A page that looks like an ordinary desktop browser. Headless Chromium announces itself
    as "HeadlessChrome" and some sites serve it a different page or none at all."""
    ua = (
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{browser.version} Safari/537.36"
    )
    context = browser.new_context(
        timezone_id=timezone_id, user_agent=ua, locale="en-US",
        viewport={"width": 1440, "height": 900},
    )
    return context.new_page()


def _blocked_hint(page) -> str:
    try:
        return f" (the page's title is {page.title()!r}; it may be blocking automated browsers)"
    except Exception:  # pragma: no cover
        return ""


def fetch_rendered_events_html(
    url: str = EVENTS_URL,
    *,
    timezone_id: str = DEFAULT_TIMEZONE,
    timeout_ms: int = 30_000,
    channel: str | None = None,
    no_sandbox: bool = False,
) -> str:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise ScrapeError(
            "Playwright is not installed. Run: pip install 'ucla-rec-api[scrape]'"
        ) from exc

    safe_url = redact_url(url)
    args = ["--disable-blink-features=AutomationControlled"] + (["--no-sandbox"] if no_sandbox else [])
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, channel=channel, args=args)
        except PlaywrightError as exc:
            raise ScrapeError(f"could not start a browser: {exc}") from exc
        try:
            page = _new_page(browser, timezone_id)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:  # let the grid's own data request finish before judging it empty
                    page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 15_000))
                except PlaywrightTimeout:
                    pass
                try:
                    page.wait_for_selector(ROWS_SELECTOR, timeout=min(timeout_ms, 15_000), state="attached")
                except PlaywrightTimeout:
                    # No rows: accept that only if the grid itself says there is no data.
                    page.wait_for_selector(NODATA_SELECTOR, timeout=timeout_ms, state="attached")
            except PlaywrightTimeout as exc:
                raise ScrapeError(
                    f"the events grid did not fill in at {safe_url} within {timeout_ms} ms" + _blocked_hint(page)
                ) from exc
            except PlaywrightError as exc:
                raise ScrapeError(f"could not load {safe_url}: {exc.message}") from exc
            page.wait_for_timeout(500)  # let the last rows finish drawing
            return page.content()
        finally:
            browser.close()


def _wait_for_grid(page, timeout_ms: int, timeout_error) -> None:
    """Wait until the desktop grid has rows, or says it has none, then let it finish drawing."""
    try:  # let the grid's own data request finish before judging it empty
        page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 15_000))
    except timeout_error:
        pass
    try:
        page.wait_for_selector(ROWS_SELECTOR, timeout=min(timeout_ms, 15_000), state="attached")
    except timeout_error:
        page.wait_for_selector(NODATA_SELECTOR, timeout=timeout_ms, state="attached")
    page.wait_for_timeout(500)


def _signature(page) -> str:
    return page.eval_on_selector_all(ROWS_SELECTOR, "els => els.map(e => e.innerText).join('|')")


def fetch_rendered_events_days(
    url: str = EVENTS_URL,
    *,
    days: int = 7,
    timezone_id: str = DEFAULT_TIMEZONE,
    timeout_ms: int = 30_000,
    channel: str | None = None,
    no_sandbox: bool = False,
) -> EventsDays:
    """Today's page, then click "next day" until `days` days are read.

    Each page is tagged with the date the page itself says it is showing, so a
    day is never filed under the wrong date.
    """
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise ScrapeError(
            "Playwright is not installed. Run: pip install 'ucla-rec-api[scrape]'"
        ) from exc

    safe_url = redact_url(url)
    today = datetime.now(ZoneInfo(timezone_id)).date()
    pages: list[tuple[date, str]] = []
    note: str | None = None
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=True, channel=channel,
                args=["--disable-blink-features=AutomationControlled"] + (["--no-sandbox"] if no_sandbox else []),
            )
        except PlaywrightError as exc:
            raise ScrapeError(f"could not start a browser: {exc}") from exc
        try:
            page = _new_page(browser, timezone_id)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                _wait_for_grid(page, timeout_ms, PlaywrightTimeout)
            except PlaywrightTimeout as exc:
                raise ScrapeError(
                    f"the events grid did not fill in at {safe_url} within {timeout_ms} ms" + _blocked_hint(page)
                ) from exc
            except PlaywrightError as exc:
                raise ScrapeError(f"could not load {safe_url}: {exc.message}") from exc

            for i in range(days):
                label = page.locator(LABEL_SELECTOR).first.inner_text() if page.locator(LABEL_SELECTOR).count() else ""
                shown = parse_page_date(label)
                if shown is None:
                    shown = (pages[-1][0] + timedelta(days=1)) if pages else today
                pages.append((shown, page.content()))
                if i == days - 1:
                    break
                try:
                    before, rows_before = label, _signature(page)
                    page.click(NEXT_SELECTOR, timeout=10_000)
                    page.wait_for_function(
                        "([sel, prev]) => { const el = document.querySelector(sel);"
                        " return !!el && el.textContent.trim() !== prev; }",
                        arg=[LABEL_SELECTOR, before], timeout=10_000,
                    )
                    page.wait_for_timeout(800)  # the new day's data is requested after the date changes
                    _wait_for_grid(page, timeout_ms, PlaywrightTimeout)
                    if _signature(page) == rows_before and not page.locator(NODATA_SELECTOR).count():
                        page.wait_for_timeout(1500)  # same rows as yesterday: make sure it is not a stale grid
                except (PlaywrightTimeout, PlaywrightError) as exc:
                    note = (f"read {len(pages)} of {days} days: could not move on from "
                            f"{pages[-1][0].isoformat()} ({type(exc).__name__})")
                    break
            return EventsDays(pages, note)
        finally:
            browser.close()