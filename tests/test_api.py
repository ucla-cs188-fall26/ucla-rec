from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rec_api import create_app
from rec_api.config import Settings

FIXTURE = Path(__file__).parent / "fixtures" / "wooden_counts.html"
AS_OF = datetime(2026, 11, 12, 1, 31, tzinfo=timezone.utc)  # 05:31 PM Pacific


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def html():
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def clock():
    return Clock(AS_OF + timedelta(minutes=10))


@pytest.fixture
def client(clock):
    app = create_app(
        Settings(database_url="sqlite://"), clock=clock
    )
    return TestClient(app)


def make_wooden(client):
    r = client.put(
        "/v1/facilities/wooden-center",
        json={"name": "John Wooden Center", "type": "gym"},
    )
    assert r.status_code == 200
    return r


def ingest(client, html, facility="wooden-center", **extra):
    body = {"facility_id": facility, "source_id": "connect2-wooden", "content": html, **extra}
    return client.post("/v1/ingest/activity", json=body)


# --- basics ------------------------------------------------------------------


def test_health(client):
    assert client.get("/v1/health").json() == {"status": "ok"}








# --- facilities --------------------------------------------------------------


def test_create_update_and_read_a_facility(client):
    r = make_wooden(client)
    assert r.json()["id"] == "wooden-center"
    client.put("/v1/facilities/wooden-center", json={"name": "Wooden Center", "type": "gym"})
    got = client.get("/v1/facilities/wooden-center").json()
    assert got["name"] == "Wooden Center"
    assert [f["id"] for f in client.get("/v1/facilities").json()] == ["wooden-center"]


def test_unknown_facility_is_a_404_with_the_error_shape(client):
    r = client.get("/v1/facilities/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_bad_facility_id_and_bad_type_are_rejected(client):
    r = client.put("/v1/facilities/Bad_ID", json={"name": "X"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_input"
    r = client.put("/v1/facilities/ok-id", json={"name": "X", "type": "spaceship"})
    assert r.status_code == 422


# --- ingest and activity -----------------------------------------------------


def test_activity_is_null_before_anything_is_ingested(client):
    make_wooden(client)
    r = client.get("/v1/facilities/wooden-center/activity")
    assert r.status_code == 200
    assert r.json() == {"facility_id": "wooden-center", "official": None, "reported": None}


def test_ingest_needs_an_existing_facility(client, html):
    r = ingest(client, html)  # facility not created yet
    assert r.status_code == 404


def test_ingest_then_read_back(client, html):
    make_wooden(client)
    r = ingest(client, html)
    assert r.status_code == 201
    assert r.json() == {
        "status": "published",
        "facility_id": "wooden-center",
        "source_id": "connect2-wooden",
        "zones": 8,
        "as_of": "2026-11-12T01:31:00Z",
    }

    official = client.get("/v1/facilities/wooden-center/activity").json()["official"]
    assert official["as_of"] == "2026-11-12T01:31:00Z"
    assert official["stale"] is False
    assert len(official["zones"]) == 8
    collins = official["zones"][0]
    assert collins["zone_id"] == "collins-court"
    assert collins["capacity"] == 1808
    assert collins["band"] == "low"


def test_staleness_is_worked_out_when_read(client, clock, html):
    make_wooden(client)
    ingest(client, html)
    path = "/v1/facilities/wooden-center/activity"
    assert client.get(path).json()["official"]["stale"] is False
    clock.t = AS_OF + timedelta(minutes=31)  # no new scrape, time just passes
    assert client.get(path).json()["official"]["stale"] is True


def test_newest_scrape_wins(client, clock, html):
    make_wooden(client)
    ingest(client, html)
    newer = html.replace("Updated: 11/11/2026 05:31 PM", "Updated: 11/11/2026 05:41 PM")
    newer = newer.replace("Last Count: 30", "Last Count: 31")
    clock.t = AS_OF + timedelta(minutes=12)
    assert ingest(client, newer).status_code == 201

    official = client.get("/v1/facilities/wooden-center/activity").json()["official"]
    assert official["as_of"] == "2026-11-12T01:41:00Z"
    cardio = next(z for z in official["zones"] if z["zone_id"] == "cardio-zone")
    assert cardio["count"] == 31


def test_unreadable_page_is_a_422_with_a_reason(client):
    make_wooden(client)
    r = ingest(client, '<html><body><div id="chartContainer"></div></body></html>')
    assert r.status_code == 422
    assert "not rendered" in r.json()["error"]["message"]
    # nothing was stored
    assert client.get("/v1/facilities/wooden-center/activity").json()["official"] is None


def test_unknown_timezone_is_a_422(client, html):
    make_wooden(client)
    r = ingest(client, html, source_timezone="Mars/Olympus")
    assert r.status_code == 422
    assert "time zone" in r.json()["error"]["message"]


def test_activity_list_covers_every_facility(client, html):
    make_wooden(client)
    client.put("/v1/facilities/bfit", json={"name": "Bruin Fitness Center", "type": "fitness_center"})
    ingest(client, html)
    rows = client.get("/v1/activity").json()
    by_id = {r["facility_id"]: r for r in rows}
    assert set(by_id) == {"bfit", "wooden-center"}
    assert by_id["bfit"]["official"] is None
    assert by_id["wooden-center"]["official"] is not None


def test_data_survives_a_restart(tmp_path, clock, html):
    url = f"sqlite:///{tmp_path / 'rec.db'}"
    settings = Settings(database_url=url)

    first = TestClient(create_app(settings, clock=clock))
    make_wooden(first)
    assert ingest(first, html).status_code == 201

    second = TestClient(create_app(settings, clock=clock))  # new app, same file
    official = second.get("/v1/facilities/wooden-center/activity").json()["official"]
    assert official["as_of"] == "2026-11-12T01:31:00Z"
    assert len(official["zones"]) == 8
