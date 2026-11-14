import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rec_api import create_app
from rec_api.config import Settings
from rec_normalizers import ParseError, parse_vems_events
from rec_normalizers.vems_events import classify, split_location
from rec_scrapers.events_cli import main as events_cli

FIXTURE = Path(__file__).parent / "fixtures" / "browse_events_rows.html"
DAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)  # 10 AM Pacific, same day


@pytest.fixture(scope="module")
def html():
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def events(html):
    return parse_vems_events(html, DAY)


@pytest.fixture
def client():
    return TestClient(create_app(Settings(database_url="sqlite://"), clock=lambda: NOW))


def ingest(client, html, **extra):
    body = {"source_id": "ucla-reserve-events", "content": html, "event_date": "2026-11-12", **extra}
    return client.post("/v1/ingest/events", json=body)


# --- parser -----------------------------------------------------------------


def test_reads_every_row(events):
    assert len(events) == 50


def test_first_row_times_are_pacific_converted_to_utc(events):
    e = events[0]
    assert (e.name, e.location, e.venue, e.space) == (
        "Custodial Cleaning", "JWC - Yates Gym", "JWC", "Yates Gym",
    )
    # 12:00 AM to 12:30 AM PST on 2026-11-12 is 08:00 to 08:30 UTC
    assert e.start == datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)
    assert e.end == datetime(2026, 11, 12, 8, 30, tzinfo=timezone.utc)
    assert not e.all_day and not e.cancelled


def test_dst_is_respected():
    html = FIXTURE.read_text(encoding="utf-8")
    summer = parse_vems_events(html, date(2026, 7, 1))[0]
    assert summer.start == datetime(2026, 7, 1, 7, 0, tzinfo=timezone.utc)  # PDT


def test_names_are_cleaned(events):
    names = {e.name for e in events}
    assert "DIA Women's Volleyball Games" in names  # entity decoded, spaces trimmed
    assert "GSRC" in names
    assert all(n == n.strip() and "  " not in n for n in names)


def test_sorted_by_start(events):
    assert [e.start for e in events] == sorted(e.start for e in events)


def test_location_pieces(events):
    pauley = next(e for e in events if e.venue == "Pauley")
    assert pauley.space == "Pavilion Club - ALL"
    assert split_location("Park Pool - PP - All") == ("Park Pool", "PP - All")
    assert split_location("Somewhere") == ("Somewhere", None)
    assert split_location(None) == (None, None)


def test_kinds(events):
    by_name = {e.name: e.kind for e in events}
    assert by_name["Open Recreation Basketball"] == "open_recreation"
    assert by_name["Lap Swimming (FP) 2026"] == "open_recreation"
    assert by_name["Custodial Cleaning"] == "maintenance"
    assert by_name["JWC Seismic Improvement Project"] == "maintenance"
    assert by_name["BHIPOn-Class- Fitwell"] == "class"
    assert by_name["Club Swimming 26-27"] == "club_sport"
    assert by_name["DIA Golf Practice"] == "athletics"
    assert by_name["UCLA Women's Rowing"] == "athletics"
    assert classify("Something unrecognised") == "other"


def test_run_past_midnight():
    row = FIXTURE.read_text(encoding="utf-8").replace(
        'aria-label="Start Time 12:00 AM">12:00 AM', 'aria-label="Start Time 11:00 PM">11:00 PM', 1
    )
    e = next(e for e in parse_vems_events(row, DAY) if e.name == "Custodial Cleaning")
    assert e.end > e.start  # 11:00 PM to 12:30 AM the next day


GRID = """<div class="dx-datagrid-rowsview"><table><tbody class="event-grid">{rows}</tbody></table></div>"""


def row(cls, start, end, name, place, anchor_cls=""):
    return f"""<tr class="{cls}"><td aria-label="Start Time {start}">{start}</td>
    <td aria-label="End Time {end}">{end}</td><td aria-label="Time Zone PT">PT</td>
    <td><div><a class="{anchor_cls}" href="#">{name}</a></div></td>
    <td><a href="#" title="{place}">{place}</a></td></tr>"""


def test_cancelled_row_is_flagged():
    html = GRID.format(rows=row("oddRows row-cancelled", "9:00 AM", "10:00 AM", "Yoga", "SAC - Room 4", "grey-text"))
    (e,) = parse_vems_events(html, DAY)
    assert e.cancelled


def test_all_day_row_has_no_time_cells():
    html = GRID.format(
        rows='<tr class="evenRows holiday"><td><div><a href="#">Veterans Day</a></div></td></tr>'
    )
    (e,) = parse_vems_events(html, DAY)
    assert e.all_day and e.name == "Veterans Day" and e.location is None
    assert (e.end - e.start).days == 1


def test_empty_grid_is_not_an_error():
    assert parse_vems_events(GRID.format(rows=""), DAY) == []


def test_unrelated_page_is_refused():
    with pytest.raises(ParseError, match="no events grid"):
        parse_vems_events("<html><body><p>Sign in</p></body></html>", DAY)


# --- API --------------------------------------------------------------------


def test_ingest_and_read_back(client, html):
    r = ingest(client, html)
    assert r.status_code == 201
    body = r.json()
    assert body["events"] == 50 and body["replaced"] == 0
    assert body["by_kind"]["open_recreation"] == 9

    got = client.get("/v1/events", params={"date": "2026-11-12"}).json()
    assert len(got) == 50
    assert got[0]["start"] == "2026-11-12T08:00:00Z"
    assert got[0]["status"] == "scheduled"


def test_date_defaults_to_today_in_los_angeles(client, html):
    ingest(client, html)
    assert len(client.get("/v1/events").json()) == 50
    assert client.get("/v1/events", params={"date": "2026-11-13"}).json() == []


def test_rescrape_replaces_instead_of_duplicating(client, html):
    ingest(client, html)
    r = ingest(client, html)
    assert r.json()["replaced"] == 50
    assert len(client.get("/v1/events").json()) == 50


def test_other_dates_and_sources_are_kept(client, html):
    ingest(client, html)
    ingest(client, html, event_date="2026-11-13")
    ingest(client, html, source_id="another-source")
    assert len(client.get("/v1/events", params={"date": "2026-11-13"}).json()) == 50
    assert len(client.get("/v1/events").json()) == 100  # two sources on the 12th


def test_filters(client, html):
    ingest(client, html)
    opens = client.get("/v1/events", params={"kind": "open_recreation"}).json()
    assert len(opens) == 9 and {e["kind"] for e in opens} == {"open_recreation"}
    two = client.get("/v1/events", params={"kind": "open_recreation,class"}).json()
    assert len(two) == 12
    pools = client.get("/v1/events", params={"venue": "sac pool"}).json()
    assert len(pools) == 8
    assert client.get("/v1/events", params={"kind": "party"}).status_code == 422


def test_events_link_to_the_facility_that_declares_the_venue(client, html):
    ingest(client, html)
    assert all(e["facility_id"] is None for e in client.get("/v1/events").json())

    client.put(
        "/v1/facilities/wooden-center",
        json={"name": "John Wooden Center", "type": "gym", "venues": ["jwc"]},  # case ignored
    )
    ingest(client, html)
    wooden = client.get("/v1/events", params={"facility_id": "wooden-center"}).json()
    assert len(wooden) == 17 and {e["venue"] for e in wooden} == {"JWC"}


def test_cancelled_hidden_unless_asked(client):
    page = GRID.format(
        rows=row("evenRows", "8:00 AM", "9:00 AM", "Open Recreation", "SAC - Room 4")
        + row("oddRows row-cancelled", "9:00 AM", "10:00 AM", "Yoga", "SAC - Room 4", "grey-text")
    )
    ingest(client, page)
    assert [e["name"] for e in client.get("/v1/events").json()] == ["Open Recreation"]
    both = client.get("/v1/events", params={"include_cancelled": "true"}).json()
    assert [e["status"] for e in both] == ["scheduled", "cancelled"]


def test_bad_pages_and_inputs(client):
    r = ingest(client, "<html><body>Sign in</body></html>")
    assert r.status_code == 422 and "no events grid" in r.json()["error"]["message"]
    assert ingest(client, GRID.format(rows=""), source_timezone="Mars/Base").status_code == 422
    assert ingest(client, GRID.format(rows=""), event_date="tomorrow").status_code == 422
    assert client.get("/v1/events").json() == []  # nothing stored from failures


def test_empty_day_publishes_zero_events(client):
    r = ingest(client, GRID.format(rows=""))
    assert r.status_code == 201 and r.json()["events"] == 0


# --- CLI --------------------------------------------------------------------


def test_cli_parses_a_saved_page(capsys):
    assert events_cli(["--html-file", str(FIXTURE), "--date", "2026-11-12"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["count"] == 50 and out["events"][0]["name"] == "Custodial Cleaning"


def test_cli_rejects_a_bad_date(capsys):
    assert events_cli(["--html-file", str(FIXTURE), "--date", "12/11/2026"]) == 2
    assert "--date" in capsys.readouterr().err


def test_cli_reports_a_wrong_page(tmp_path, capsys):
    page = tmp_path / "x.html"
    page.write_text("<html><body>nope</body></html>")
    assert events_cli(["--html-file", str(page), "--date", "2026-11-12"]) == 2
    assert "no events grid" in capsys.readouterr().err


# --- the one endpoint for every source ----------------------------------------

COUNTS = Path(__file__).parent / "fixtures" / "wooden_counts.html"


def unified(client, content, **extra):
    return client.post(
        "/v1/ingest", json={"source_id": "s", "content": content, **extra}
    )


def make_facilities(client):
    client.put("/v1/facilities/wooden-center",
               json={"name": "John Wooden Center", "type": "gym", "venues": ["JWC"]})
    client.put("/v1/facilities/sunset-rec",
               json={"name": "Sunset Rec", "type": "gym", "venues": ["SCRC"]})


def test_unified_endpoint_takes_a_counts_page(client):
    make_facilities(client)
    r = unified(client, COUNTS.read_text(encoding="utf-8"), facility_id="wooden-center")
    assert r.status_code == 201
    body = r.json()
    assert body["type"] == "connect2_counts" and body["zones"] == 8
    assert body["facility_id"] == "wooden-center"
    assert client.get("/v1/facilities/wooden-center/activity").json()["official"] is not None


def test_unified_endpoint_takes_an_events_page_and_splits_by_facility(client, html):
    make_facilities(client)
    r = unified(client, html, event_date="2026-11-12")
    body = r.json()
    assert r.status_code == 201 and body["type"] == "events" and body["events"] == 50
    assert body["by_facility"]["wooden-center"] == 17
    assert body["by_facility"]["sunset-rec"] == 2
    assert body["by_facility"]["unassigned"] == 31
    assert len(client.get("/v1/events", params={"facility_id": "sunset-rec"}).json()) == 2


def test_unified_events_default_to_today_in_los_angeles(client, html):
    assert unified(client, html).json()["event_date"] == "2026-11-12"


def test_unified_events_can_be_pinned_to_one_facility(client, html):
    make_facilities(client)
    body = unified(client, html, facility_id="sunset-rec").json()
    assert body["by_facility"] == {"sunset-rec": 50}


def test_unified_endpoint_errors(client, html):
    counts = COUNTS.read_text(encoding="utf-8")
    r = unified(client, counts)  # no facility
    assert r.status_code == 422 and "facility_id is required" in r.json()["error"]["message"]
    assert unified(client, counts, facility_id="nope").status_code == 404
    assert unified(client, html, facility_id="nope").status_code == 404
    r = unified(client, "<html><body>Sign in</body></html>")
    assert r.status_code == 422 and "could not tell what this is" in r.json()["error"]["message"]
    assert unified(client, html, source_timezone="Mars/Base").status_code == 422


def test_detect_page_type(html):
    from rec_normalizers import detect_page_type

    assert detect_page_type(html) == "events"
    assert detect_page_type(COUNTS.read_text(encoding="utf-8")) == "connect2_counts"
    assert detect_page_type("<p>hello</p>") is None


def test_facility_venues_roundtrip(client):
    r = client.put("/v1/facilities/wooden-center",
                   json={"name": "John Wooden Center", "venues": ["JWC", "Pauley"]})
    assert r.json()["venues"] == ["JWC", "Pauley"]
    assert client.get("/v1/facilities/wooden-center").json()["venues"] == ["JWC", "Pauley"]
    r = client.put("/v1/facilities/old", json={"name": "No venues given"})
    assert r.json()["venues"] == []


def test_database_made_before_venues_is_upgraded(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE facilities (id VARCHAR(80) PRIMARY KEY, name VARCHAR(200), "
                "type VARCHAR(40), updated_at DATETIME)")
    con.execute("INSERT INTO facilities VALUES ('old','Old','gym','2026-01-01 00:00:00')")
    con.commit()
    con.close()
    c = TestClient(create_app(Settings(database_url=f"sqlite:///{db}"), clock=lambda: NOW))
    assert c.get("/v1/facilities/old").json()["venues"] == []
    c.put("/v1/facilities/old", json={"name": "Old", "venues": ["X"]})
    assert c.get("/v1/facilities/old").json()["venues"] == ["X"]
