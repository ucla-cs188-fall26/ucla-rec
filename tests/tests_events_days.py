"""Reading several days from the live events page.

A local page stands in for UCLA's: a daily view with a date heading and a "next
day" arrow, a grid that is redrawn some time AFTER the date changes (so a scraper
that reads too early sees yesterday's rows), and a mobile grid whose "No data"
notice is always showing.
"""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from rec_normalizers import parse_vems_events
from rec_scrapers import ScrapeError
from rec_scrapers.events import fetch_rendered_events_days, parse_page_date
from rec_scrapers.run import ConfigError, load_config, main

from test_pipeline import api, get_json  # noqa: F401  (the real-server fixture)

FIX = Path(__file__).parent / "fixtures"
BROWSER = dict(channel="chrome", no_sandbox=True)
needs_browser = pytest.mark.skipif(
    not (shutil.which("google-chrome") or shutil.which("chrome") or shutil.which("chromium")),
    reason="needs a Chrome or Chromium install",
)


def day_rows():
    """The real fixture's rows, split into three 'days': 3 rows, 2 rows, none."""
    soup = BeautifulSoup((FIX / "browse_events_rows.html").read_text(encoding="utf-8"), "html.parser")
    rows = [str(r) for r in soup.select("tbody.event-grid tr.evenRows, tbody.event-grid tr.oddRows")]
    return [rows[0:3], rows[3:5], []]


def write_page(tmp_path, delay_ms=400, start="2026-11-13"):
    labels = ["Friday, November 13th 2026", "Saturday, November 14th 2026", "Sunday, November 15th 2026",
              "Monday, November 16th 2026"]
    days = day_rows() + [day_rows()[0]]  # day four repeats day one's rows exactly
    page = f"""<!doctype html><html><body>
<div id="dailyContainer"><div class="text-center">
  <button class="nav-button"><i class="fa fa-chevron-left"></i></button>
  <span aria-label="" id="label"></span>
  <button class="nav-button" id="next"><i class="fa fa-chevron-right"></i></button></div>
  <div id="eventResults"><table><tbody class="event-grid" id="rows"></tbody></table>
    <div class="dx-datagrid-nodata dx-hidden" id="nodata">No data</div></div></div>
<div id="mobileEventResults"><div class="dx-datagrid-nodata">No data</div></div>
<script>
  const labels = {json.dumps(labels)}, days = {json.dumps(days)};
  let i = 0;
  const label = document.getElementById("label");
  function draw() {{
    document.getElementById("rows").innerHTML = days[i].join("");
    document.getElementById("nodata").classList.toggle("dx-hidden", days[i].length > 0);
  }}
  function setLabel() {{ label.textContent = labels[i]; label.setAttribute("aria-label", labels[i]); }}
  setLabel(); draw();
  document.getElementById("next").onclick = () => {{
    i = Math.min(i + 1, days.length - 1);
    setLabel();                          // the date changes at once...
    setTimeout(draw, {delay_ms});        // ...the grid catches up later
  }};
</script></body></html>"""
    path = tmp_path / "events.html"
    path.write_text(page, encoding="utf-8")
    return path.as_uri()


# --- reading the date off the page -------------------------------------------------

def test_the_pages_own_date_is_read():
    assert parse_page_date("Friday, November 13th 2026") == date(2026, 11, 13)
    assert parse_page_date("Monday, December 1st 2026") == date(2026, 12, 1)
    assert parse_page_date("Tuesday, March 3rd 2026") == date(2026, 3, 3)
    assert parse_page_date("nothing here") is None


# --- the browser ----------------------------------------------------------------------

@needs_browser
def test_reads_each_day_under_the_date_the_page_showed(tmp_path):
    got = fetch_rendered_events_days(write_page(tmp_path), days=3, **BROWSER)
    assert got.note is None
    assert [d for d, _ in got.pages] == [date(2026, 11, 13), date(2026, 11, 14), date(2026, 11, 15)]
    counts = [len(parse_vems_events(html, d, "America/Los_Angeles")) for d, html in got.pages]
    assert counts == [3, 2, 0]


@needs_browser
def test_a_grid_that_redraws_late_is_not_read_early(tmp_path):
    # 1.2 s between the date changing and the rows changing: reading at once gives the old day
    got = fetch_rendered_events_days(write_page(tmp_path, delay_ms=1200), days=2, **BROWSER)
    assert len(parse_vems_events(got.pages[1][1], got.pages[1][0], "America/Los_Angeles")) == 2


@needs_browser
def test_the_mobile_grids_no_data_notice_does_not_count_as_loaded(tmp_path):
    # Day three is empty ("No data" under #eventResults); day four has rows again.
    got = fetch_rendered_events_days(write_page(tmp_path), days=4, **BROWSER)
    counts = [len(parse_vems_events(h, d, "America/Los_Angeles")) for d, h in got.pages]
    assert counts == [3, 2, 0, 3]


@needs_browser
def test_a_page_with_no_next_arrow_gives_the_days_it_has(tmp_path):
    uri = write_page(tmp_path)
    page = tmp_path / "events.html"
    page.write_text(page.read_text(encoding="utf-8").replace("fa-chevron-right", "fa-other"), encoding="utf-8")
    got = fetch_rendered_events_days(uri, days=3, **BROWSER)
    assert len(got.pages) == 1 and got.note and "1 of 3" in got.note


# --- the runner -------------------------------------------------------------------------

def config(tmp_path, url, **source):
    cfg = {
        "facilities": [{"id": "wooden-center", "name": "John Wooden Center", "type": "gym", "venues": ["JWC"]}],
        "sources": [{"id": "ucla-reserve-events", "type": "events", "url": url, **source}],
    }
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(cfg))
    return path


@needs_browser
def test_runner_posts_one_batch_per_day(api, tmp_path, capsys):
    cfg = config(tmp_path, write_page(tmp_path), days=3)
    assert main(["--config", str(cfg), "--api", api, "--browser-channel", "chrome", "--no-sandbox"]) == 0
    res = json.loads(capsys.readouterr().out)["results"][0]
    assert [(d["date"], d["events"]) for d in res["days"]] == [
        ("2026-11-13", 3), ("2026-11-14", 2), ("2026-11-15", 0)]
    assert len(get_json(f"{api}/v1/events?date=2026-11-14&limit=500")) == 2
    assert len(get_json(f"{api}/v1/events?from=2026-11-13&to=2026-11-15&limit=500")) == 5


@needs_browser
def test_running_again_replaces_each_day_instead_of_doubling(api, tmp_path, capsys):
    cfg = config(tmp_path, write_page(tmp_path), days=2)
    args = ["--config", str(cfg), "--api", api, "--browser-channel", "chrome", "--no-sandbox"]
    main(args); main(args)
    capsys.readouterr()
    assert len(get_json(f"{api}/v1/events?from=2026-11-13&to=2026-11-14&limit=500")) == 5


@needs_browser
def test_days_on_the_command_line_beats_the_config(api, tmp_path, capsys):
    cfg = config(tmp_path, write_page(tmp_path), days=3)
    main(["--config", str(cfg), "--api", api, "--days", "1", "--browser-channel", "chrome", "--no-sandbox"])
    res = json.loads(capsys.readouterr().out)["results"][0]
    assert "days" not in res and res["response"]["event_date"] == "2026-11-13"


def test_days_must_be_a_sensible_number(tmp_path):
    for bad in (0, 32, "7", True):
        with pytest.raises(ConfigError, match="days"):
            load_config(config(tmp_path, "https://example.com", days=bad))
    assert load_config(config(tmp_path, "https://example.com", days=14))["sources"][0]["days"] == 14


def test_days_flag_is_checked(tmp_path, capsys):
    assert main(["--config", str(config(tmp_path, "https://example.com")), "--days", "0"]) == 2