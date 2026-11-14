"""Load a live Connect2Concepts counts page in a headless browser.

The page's server response has an empty chart container. A script fills it in,
so a plain HTTP request gets no zones. This module runs the page in a real
browser, waits for the zones to appear, and returns the finished HTML for
rec_normalizers.parse_connect2_counts.
"""

from __future__ import annotations

from urllib.parse import urlsplit

DEFAULT_TIMEZONE = "America/Los_Angeles"
ZONES_SELECTOR = "#chartContainer div.barChart"


class ScrapeError(RuntimeError):
    """The page could not be loaded or never showed any zones."""


def redact_url(url: str) -> str:
    """Scheme, host and path only. The query string holds an access key."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def fetch_rendered_html(
    url: str,
    *,
    timezone_id: str = DEFAULT_TIMEZONE,
    timeout_ms: int = 20_000,
    channel: str | None = None,
    no_sandbox: bool = False,
) -> str:
    """Open `url`, wait for at least one zone, return the rendered HTML.

    timezone_id: the page prints "Updated" times in the browser's zone, so this
        must match the zone the parser is told to expect (default Los Angeles).
    channel: use an installed browser such as "chrome" instead of Playwright's
        bundled Chromium.
    no_sandbox: needed when running as root inside a container.
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
    dialogs: list[str] = []
    args = ["--no-sandbox"] if no_sandbox else []

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, channel=channel, args=args)
        except PlaywrightError as exc:
            raise ScrapeError(f"could not start a browser: {exc}") from exc

        try:
            context = browser.new_context(timezone_id=timezone_id)
            page = context.new_page()

            def on_dialog(dialog):
                # The widget calls alert() when its data request fails.
                dialogs.append(dialog.message)
                dialog.dismiss()

            page.on("dialog", on_dialog)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_selector(ZONES_SELECTOR, timeout=timeout_ms)
            except PlaywrightTimeout as exc:
                detail = f" The page said: {dialogs[0]!r}." if dialogs else ""
                raise ScrapeError(
                    f"no zones appeared at {safe_url} within {timeout_ms} ms.{detail}"
                ) from exc
            except PlaywrightError as exc:
                raise ScrapeError(f"could not load {safe_url}: {exc.message}") from exc

            return page.content()
        finally:
            browser.close()
