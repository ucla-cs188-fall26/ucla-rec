"""The pool calendar PDF: parse it, store it, run it from a config file."""

import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from rec_api import create_app
from rec_api.config import Settings
from rec_normalizers import ParseError, detect_page_type, parse_pool_schedule
from rec_scrapers.pdf import pdf_to_content
from rec_scrapers.run import ConfigError, load_config, main

from test_pipeline import api, get_json  # noqa: F401  (the real-server fixture)

FIX = Path(__file__).parent / "fixtures"
LA = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def content():
    return (FIX / "pool_schedule_words.json").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def events(content):
    return parse_pool_schedule(content)[0]


def on(events, day, venue=None):
    return [e for e in events
            if e.start.astimezone(LA).date() == day and (venue is None or e.venue == venue)]


def hours(e):
    return e.start.astimezone(LA).strftime("%H:%M"), e.end.astimezone(LA).strftime("%H:%M")


# --- parser -----------------------------------------------------------------

def test_detected_as_a_pool_calendar(content):
    assert detect_page_type(content) == "pool_schedule"


def test_covers_every_day_of_the_calendar(content, events):
    days = {e.start.astimezone(LA).date() for e in events}
    assert min(days) == date(2026, 11, 9) and max(days) == date(2026, 12, 27)
    assert len(days) == 49  # nothing skipped, nothing doubled
    assert parse_pool_schedule(content)[1] == []  # every line understood


def test_open_hours_and_activities_for_a_normal_day(events):
    mon = on(events, date(2026, 11, 9))
    park = [e for e in mon if e.venue == "Park Pool"]
    assert [(e.kind, e.name, *hours(e)) for e in park] == [
        ("pool_hours", "Open", "11:00", "20:00"),
        ("pool_activity", "Open Rec Diving", "15:00", "17:00"),
        ("pool_activity", "Club Art Swim 2 lns deep", "18:00", "20:00"),
    ]
    family = [e for e in mon if e.venue == "Family Pool"]
    assert [hours(e) for e in family if e.kind == "pool_hours"] == [("06:00", "10:00"), ("12:00", "18:00")]
    assert any(e.name == "Adult Lessons Lap Lanes" and hours(e) == ("17:00", "18:00") for e in family)


def test_a_line_belongs_to_its_own_day_not_the_next(events):
    # "Adult Lessons ... 5p-6p" ends right against the next day's "SAC - 11am-1pm".
    tue = on(events, date(2026, 11, 10), "Student Activities Center Pool")
    assert [(e.name, *hours(e)) for e in tue] == [
        ("Open", "11:00", "13:00"), ("Aqua Tabata BH Area", "12:00", "13:00")]


def test_closed_with_and_without_a_reason(events):
    sac = on(events, date(2026, 11, 11), "Student Activities Center Pool")
    assert [(e.kind, e.name, e.all_day) for e in sac] == [("closed", "Closed", True)]
    dec15 = on(events, date(2026, 12, 15))
    assert {(e.venue, e.name) for e in dec15 if e.kind == "closed"} == {
        ("Park Pool", "Closed (SCRC Maintenance)"), ("Family Pool", "Closed (SCRC Maintenance)"),
        ("Student Activities Center Pool", "Closed (Deck Maintenance)")}


def test_holiday_banner_closes_every_pool(events):
    for day in (26, 27, 28):
        closed = on(events, date(2026, 11, day))
        assert {e.venue for e in closed} == {"Park Pool", "Family Pool", "Student Activities Center Pool"}
        assert all(e.kind == "closed" and e.all_day for e in closed)


def test_tbd_is_not_guessed(events):
    north = on(events, date(2026, 12, 14), "North Pool")
    assert [(e.kind, e.name) for e in north] == [("tbd", "Hours not yet posted")]


def test_month_rollover_and_the_december_first_label(events):
    # Nov 30 is followed by the cell printed "DECEMBER 1ST".
    assert on(events, date(2026, 11, 30)) and on(events, date(2026, 12, 1))
    assert any(hours(e) == ("11:00", "20:00") for e in on(events, date(2026, 12, 1), "Park Pool"))


def test_times_are_utc_and_follow_los_angeles(events):
    e = on(events, date(2026, 11, 9), "Park Pool")[0]
    assert e.start == datetime(2026, 11, 9, 19, 0, tzinfo=timezone.utc)  # 11 AM PST


def test_not_a_calendar_is_refused():
    with pytest.raises(ParseError):
        parse_pool_schedule(json.dumps({"format": "pdf_words", "pages": [{"words": []}]}))
    with pytest.raises(ParseError):
        parse_pool_schedule("{}")


def test_day_numbers_that_do_not_line_up_are_refused(content):
    doc = json.loads(content)
    words = doc["pages"][0]["words"]
    # change the printed "10" over Tuesday of week one to "11"
    w = next(w for w in words if w["text"] == "10" and w["top"] < 100)
    w["text"] = "11"
    with pytest.raises(ParseError, match="do not line up"):
        parse_pool_schedule(json.dumps(doc))


# --- the PDF itself ------------------------------------------------------------

def test_the_real_pdf_gives_the_same_result_as_the_saved_words(content):
    fresh = pdf_to_content((FIX / "pool_schedule.pdf").read_bytes())
    a, b = parse_pool_schedule(fresh)[0], parse_pool_schedule(content)[0]
    assert [(e.venue, e.kind, e.name, e.start) for e in a] == [(e.venue, e.kind, e.name, e.start) for e in b]


def test_a_file_that_is_not_a_pdf_is_refused():
    from rec_scrapers.connect2 import ScrapeError
    with pytest.raises(ScrapeError, match="not a PDF"):
        pdf_to_content(b"<html>Sign in</html>")


# --- through the API ---------------------------------------------------------------

@pytest.fixture
def client():
    c = TestClient(create_app(Settings(database_url="sqlite://"), clock=lambda: NOW))
    c.put("/v1/facilities/pools", json={
        "name": "Pools", "type": "pool",
        "venues": ["Park Pool", "Family Pool", "North Pool", "Student Activities Center Pool"]})
    return c


def ingest(client, content, **extra):
    return client.post("/v1/ingest", json={
        "source_id": "pool-calendar", "content_type": "application/json", "content": content, **extra})


def test_ingest_splits_pool_entries_to_the_pools_facility(client, content):
    r = ingest(client, content)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["type"] == "pool_schedule"
    assert (body["event_date"], body["last_date"]) == ("2026-11-09", "2026-12-27")
    assert body["by_facility"] == {"pools": body["events"]}
    assert body["skipped"] is None


def test_the_day_view_returns_that_days_hours(client, content):
    ingest(client, content)
    rows = client.get("/v1/events", params={
        "date": "2026-11-09", "facility_id": "pools", "kind": "pool_hours"}).json()
    assert sorted((r["venue"], r["start"]) for r in rows)[0][0] == "Family Pool"
    assert len(rows) == 4  # Park, Family twice, SAC


def test_closures_are_listed_for_the_events_panel(client, content):
    ingest(client, content)
    rows = client.get("/v1/events", params={
        "facility_id": "pools", "kind": "closed", "upcoming": "true", "limit": 500}).json()
    assert {r["name"] for r in rows} >= {"Closed", "Closed (SCRC Maintenance)"}
    assert all(r["all_day"] for r in rows)


def test_sending_it_again_replaces_the_whole_calendar(client, content):
    first = ingest(client, content).json()
    second = ingest(client, content).json()
    assert second["replaced"] == first["events"]
    total = client.get("/v1/events", params={"facility_id": "pools", "upcoming": "true", "limit": 500}).json()
    assert len(total) <= 500
    assert len(client.get("/v1/events", params={"date": "2026-11-09", "facility_id": "pools"}).json()) == 7


def test_a_bad_calendar_is_a_clean_422(client):
    r = ingest(client, json.dumps({"format": "pdf_words", "pages": [{"words": []}]}))
    assert r.status_code == 422 and "pool calendar" in r.json()["error"]["message"]


# --- the runner --------------------------------------------------------------------

def pool_config(tmp_path, **source):
    (tmp_path / "pool.pdf").write_bytes((FIX / "pool_schedule.pdf").read_bytes())
    cfg = {
        "facilities": [{"id": "pools", "name": "Pools", "type": "pool",
                        "venues": ["Park Pool", "Family Pool", "Student Activities Center Pool"]}],
        "sources": [{"id": "pool-calendar", "type": "pool_schedule", "pdf_file": "pool.pdf", **source}],
    }
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(cfg))
    return path


def test_runner_reads_the_pdf_file(api, tmp_path, capsys):
    assert main(["--config", str(pool_config(tmp_path)), "--api", api]) == 0
    out = json.loads(capsys.readouterr().out)
    res = out["results"][0]["response"]
    assert res["type"] == "pool_schedule" and res["last_date"] == "2026-12-27"
    rows = get_json(f"{api}/v1/events?date=2026-11-26&facility_id=pools&kind=closed")
    assert len(rows) == 3


def test_a_missing_pdf_names_the_file_and_the_rest_carry_on(api, tmp_path, capsys):
    path = pool_config(tmp_path)
    (tmp_path / "pool.pdf").unlink()
    assert main(["--config", str(path), "--api", api]) == 1
    err = json.loads(capsys.readouterr().out)["results"][0]["error"]
    assert "pool.pdf" in err


def test_a_pool_calendar_cannot_be_an_html_file(tmp_path):
    path = pool_config(tmp_path)
    cfg = json.loads(path.read_text())
    cfg["sources"][0]["html_file"] = "x.html"
    path.write_text(json.dumps(cfg))
    with pytest.raises(ConfigError, match="PDF"):
        load_config(path)


# --- the calendar view -----------------------------------------------------------

def test_each_entry_carries_the_code_printed_on_the_calendar(events):
    codes = {(e.venue, e.space) for e in events}
    assert codes == {("Park Pool", "PP"), ("Family Pool", "FP"),
                     ("Student Activities Center Pool", "SAC"), ("North Pool", "North Pool")}


def test_a_date_range_returns_every_day_in_it(client, content):
    ingest(client, content)
    rows = client.get("/v1/events", params={
        "facility_id": "pools", "from": "2026-11-09", "to": "2026-11-15", "limit": 500}).json()
    days = {r["start"][:10] for r in rows}
    assert len(days) == 7 and len(rows) > 30 and min(days) >= "2026-11-09" and max(days) <= "2026-11-16"
    # the order they were read in is kept (id), so a day lists its pools as printed
    day = sorted((r for r in rows if r["start"].startswith("2026-11-09")), key=lambda r: r["id"])
    assert [r["space"] for r in day if r["kind"] == "pool_hours"][:2] == ["PP", "FP"]


def test_a_range_needs_both_ends_in_order(client):
    assert client.get("/v1/events", params={"from": "2026-11-09"}).status_code == 422
    assert client.get("/v1/events", params={"from": "2026-11-10", "to": "2026-11-09"}).status_code == 422
