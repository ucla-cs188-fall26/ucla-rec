"""Scraper tests.

The browser tests serve a local page that, like the real Connect2 page, starts
with an empty chart container and fills it with JavaScript after a short delay.
The script prints "Updated" using the browser's local time zone, the same way
UCLA's page does, so these tests also prove the time zone setting works.
"""

import json
import shutil
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from rec_normalizers import parse_connect2_counts
from rec_scrapers import ScrapeError, fetch_rendered_html, redact_url
from rec_scrapers.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "wooden_counts.html"

needs_browser = pytest.mark.skipif(
    shutil.which("google-chrome") is None, reason="no installed Chrome to drive"
)
BROWSER = dict(channel="chrome", no_sandbox=True)


def _blocks_with_placeholder() -> list[str]:
    soup = BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "html.parser")
    blocks = [str(b) for b in soup.select("#chartContainer div.barChart")]
    assert len(blocks) == 8
    return [b.replace("Updated: 11/11/2026 05:31 PM", "Updated: __UPDATED__") for b in blocks]


GOOD_PAGE = """<html><body>
<span id="facilityName">John Wooden Center - FITWELL</span>
<div id="chartContainer"></div>
<script>
const BLOCKS = %s;
const d = new Date(Date.UTC(2026, 10, 12, 1, 31));
function fmt(date) {
  const month = (date.getMonth() + 1).toString().padStart(2, '0');
  const day = date.getDate().toString().padStart(2, '0');
  let hours = date.getHours();
  const minutes = date.getMinutes();
  const ampm = hours >= 12 ? 'PM' : 'AM';
  hours = hours %% 12; hours = hours ? hours : 12;
  return month + '/' + day + '/' + date.getFullYear() + ' ' +
    hours.toString().padStart(2, '0') + ':' + minutes.toString().padStart(2, '0') + ' ' + ampm;
}
setTimeout(function () {
  document.getElementById('chartContainer').innerHTML =
    BLOCKS.map(function (b) { return b.replace('__UPDATED__', fmt(d)); }).join('');
}, 300);
</script></body></html>
""" % json.dumps(_blocks_with_placeholder()).replace("</", "<\\/")

EMPTY_PAGE = '<html><body><div id="chartContainer"></div></body></html>'
ALERT_PAGE = (
    '<html><body><div id="chartContainer"></div>'
    "<script>alert('Error loading facility data');</script></body></html>"
)
PAGES = {"/good": GOOD_PAGE, "/empty": EMPTY_PAGE, "/alert": ALERT_PAGE}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        body = PAGES.get(path)
        if body is None:
            self.send_error(404)
            return
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def base_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join()


# --- browser path ---------------------------------------------------------


@needs_browser
def test_waits_for_the_script_to_fill_the_page(base_url):
    html = fetch_rendered_html(f"{base_url}/good?key=secret", timeout_ms=10_000, **BROWSER)
    counts = parse_connect2_counts(html)
    assert len(counts.zones) == 8
    assert counts.facility_name == "John Wooden Center - FITWELL"


@needs_browser
def test_browser_timezone_matches_parser_default(base_url):
    html = fetch_rendered_html(f"{base_url}/good", timeout_ms=10_000, **BROWSER)
    counts = parse_connect2_counts(html)  # defaults to America/Los_Angeles
    assert counts.as_of == datetime(2026, 11, 12, 1, 31, tzinfo=timezone.utc)


@needs_browser
def test_page_that_never_fills_times_out_with_a_clear_error(base_url):
    with pytest.raises(ScrapeError, match="no zones appeared"):
        fetch_rendered_html(f"{base_url}/empty?key=secret", timeout_ms=1_000, **BROWSER)


@needs_browser
def test_error_includes_the_pages_own_alert_and_hides_the_key(base_url):
    with pytest.raises(ScrapeError) as info:
        fetch_rendered_html(f"{base_url}/alert?key=secret", timeout_ms=1_500, **BROWSER)
    message = str(info.value)
    assert "Error loading facility data" in message
    assert "secret" not in message


@needs_browser
def test_cli_end_to_end_against_local_page(base_url, capsys, monkeypatch):
    monkeypatch.setenv("TEST_COUNTS_URL", f"{base_url}/good?key=secret")
    code = main(
        ["--url-env", "TEST_COUNTS_URL", "--timeout-ms", "10000",
         "--browser-channel", "chrome", "--no-sandbox"]
    )
    out = capsys.readouterr()
    assert code == 0
    data = json.loads(out.out)
    assert data["official"]["as_of"] == "2026-11-12T01:31:00Z"
    assert data["official"]["stale"] is True  # the fixed 2026 timestamp is old by now
    assert len(data["official"]["zones"]) == 8
    assert "secret" not in out.out  # access key is never printed
    assert data["source"] == f"{base_url}/good"


# --- no-browser paths -----------------------------------------------------


def test_redact_url_drops_the_query_string():
    assert redact_url("https://example.com/a/b?key=abc&x=1") == "https://example.com/a/b"


def test_cli_parses_a_saved_page_without_a_browser(capsys):
    code = main(["--html-file", str(FIXTURE)])
    out = capsys.readouterr()
    assert code == 0
    data = json.loads(out.out)
    assert data["facility_name"] == "John Wooden Center - FITWELL"
    assert [z["zone_id"] for z in data["official"]["zones"]][:2] == ["collins-court", "pardee-gym"]


def test_cli_reports_an_unrendered_saved_page(tmp_path, capsys):
    page = tmp_path / "raw.html"
    page.write_text(EMPTY_PAGE, encoding="utf-8")
    assert main(["--html-file", str(page)]) == 2
    assert "not rendered" in capsys.readouterr().err


def test_cli_reports_a_missing_environment_variable(monkeypatch, capsys):
    monkeypatch.delenv("NOPE_URL", raising=False)
    assert main(["--url-env", "NOPE_URL"]) == 2
    assert "NOPE_URL" in capsys.readouterr().err


def test_cli_reports_a_missing_file(tmp_path, capsys):
    assert main(["--html-file", str(tmp_path / "missing.html")]) == 2
    assert "error:" in capsys.readouterr().err
