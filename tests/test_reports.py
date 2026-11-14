from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rec_api import create_app
from rec_api.config import Settings
from rec_api.reports import combine, summarize

T0 = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)
EVENTS = Path(__file__).parent / "fixtures" / "browse_events_rows.html"


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


class Outbox:
    def __init__(self):
        self.sent = []

    def send_code(self, to, code):
        self.sent.append((to, code))


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def outbox():
    return Outbox()


@pytest.fixture
def client(clock, outbox):
    app = create_app(Settings(database_url="sqlite://", secret="test"), clock=clock, mailer=outbox)
    c = TestClient(app)
    c.put("/v1/facilities/hitch-courts", json={"name": "Hitch Basketball Courts", "type": "court"})
    return c


def sign_in(client, outbox, email="bruin@g.ucla.edu"):
    assert client.post("/v1/auth/code", json={"email": email}).status_code == 202
    to, code = outbox.sent[-1]
    r = client.post("/v1/auth/verify", json={"email": email, "code": code})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def report(client, headers, level, facility="hitch-courts"):
    return client.post(f"/v1/facilities/{facility}/reports", json={"level": level}, headers=headers)


# --- combining reports ---------------------------------------------------------


def test_combine_uses_the_middle_value():
    assert combine([1]) == (1.0, "median")
    assert combine([1, 3]) == (2.0, "median")  # in between, as asked
    assert combine([1, 2, 3, 3]) == (2.5, "median")


def test_five_or_more_drop_the_extremes():
    assert combine([1, 2, 2, 2, 3]) == (2.0, "trimmed_median")
    assert combine([1, 1, 3, 3, 3])[0] == 3.0  # drops one 1 and one 3 -> 1,3,3 -> 3


def test_halves_round_up_to_the_busier_level():
    out = summarize([(1, T0), (2, T0)], 45)
    assert out["score"] == 1.5 and out["level"] == 2 and out["label"] == "Moderate"
    assert summarize([], 45) is None


# --- sign-in -------------------------------------------------------------------


def test_sign_in_flow(client, outbox, clock):
    r = client.post("/v1/auth/code", json={"email": " Bruin@G.UCLA.edu "})
    assert r.status_code == 202 and r.json()["dev_code"] is None
    assert outbox.sent[0][0] == "bruin@g.ucla.edu"
    assert len(outbox.sent[0][1]) == 6
    clock.advance(seconds=61)
    headers = sign_in(client, outbox)  # a fresh code after the wait
    assert headers


def test_only_ucla_addresses(client):
    for bad in ["someone@gmail.com", "x@ucla.edu.evil.com", "x@evil.com", "nope", "a@b@ucla.edu"]:
        r = client.post("/v1/auth/code", json={"email": bad})
        assert r.status_code == 422, bad
    assert client.post("/v1/auth/code", json={"email": "ok@ucla.edu"}).status_code == 202


def test_codes_cannot_be_requested_in_a_burst(client, clock):
    assert client.post("/v1/auth/code", json={"email": "a@ucla.edu"}).status_code == 202
    r = client.post("/v1/auth/code", json={"email": "a@ucla.edu"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    clock.advance(seconds=61)
    assert client.post("/v1/auth/code", json={"email": "a@ucla.edu"}).status_code == 202


def test_wrong_code_then_lockout(client, outbox):
    client.post("/v1/auth/code", json={"email": "a@ucla.edu"})
    real = outbox.sent[-1][1]
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(5):
        r = client.post("/v1/auth/verify", json={"email": "a@ucla.edu", "code": wrong})
        assert r.status_code == 422 and "not right" in r.json()["error"]["message"]
    r = client.post("/v1/auth/verify", json={"email": "a@ucla.edu", "code": real})
    assert r.status_code == 422 and "too many" in r.json()["error"]["message"]


def test_code_expires_and_works_once(client, clock, outbox):
    client.post("/v1/auth/code", json={"email": "a@ucla.edu"})
    code = outbox.sent[-1][1]
    clock.advance(minutes=11)
    r = client.post("/v1/auth/verify", json={"email": "a@ucla.edu", "code": code})
    assert r.status_code == 422 and "expired" in r.json()["error"]["message"]

    client.post("/v1/auth/code", json={"email": "a@ucla.edu"})
    code = outbox.sent[-1][1]
    assert client.post("/v1/auth/verify", json={"email": "a@ucla.edu", "code": code}).status_code == 200
    assert client.post("/v1/auth/verify", json={"email": "a@ucla.edu", "code": code}).status_code == 422


def test_dev_code_only_when_enabled(outbox):
    app = create_app(Settings(database_url="sqlite://", show_codes=True), mailer=outbox)
    r = TestClient(app).post("/v1/auth/code", json={"email": "a@ucla.edu"})
    assert r.json()["dev_code"] == outbox.sent[-1][1]


def test_the_database_holds_no_email_or_code(outbox, tmp_path):
    import sqlite3

    db = tmp_path / "p.db"
    c = TestClient(create_app(Settings(database_url=f"sqlite:///{db}", secret="s"), mailer=outbox))
    c.put("/v1/facilities/hitch-courts", json={"name": "Hitch"})
    headers = sign_in(c, outbox, "secret.person@g.ucla.edu")
    code = outbox.sent[-1][1]
    report(c, headers, 2)
    token = headers["Authorization"].split()[1]
    con = sqlite3.connect(db)
    dump = "\n".join(
        str(row) for (t,) in con.execute("select name from sqlite_master where type='table'")
        for row in con.execute(f"select * from {t}")
    )
    assert "secret.person" not in dump and token not in dump
    assert f"'{code}'" not in dump


# --- reports ---------------------------------------------------------------------


def test_report_needs_sign_in(client):
    r = client.post("/v1/facilities/hitch-courts/reports", json={"level": 2})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    r = client.post("/v1/facilities/hitch-courts/reports", json={"level": 2},
                    headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 401


def test_session_expires(client, clock, outbox):
    headers = sign_in(client, outbox)
    clock.advance(days=31)
    assert report(client, headers, 2).status_code == 401


def test_report_validation(client, outbox):
    headers = sign_in(client, outbox)
    assert report(client, headers, 0).status_code == 422
    assert report(client, headers, 4).status_code == 422
    assert report(client, headers, 2, facility="nope").status_code == 404


def test_reports_show_up_in_activity(client, outbox):
    assert client.get("/v1/facilities/hitch-courts/activity").json()["reported"] is None
    headers = sign_in(client, outbox)
    r = report(client, headers, 3)
    assert r.status_code == 201 and r.json()["reported"]["label"] == "Busy"
    got = client.get("/v1/facilities/hitch-courts/activity").json()["reported"]
    assert got["level"] == 3 and got["reports"] == 1 and got["window_minutes"] == 45
    assert client.get("/v1/activity").json()[0]["reported"]["level"] == 3


def test_one_voice_per_person_newest_wins(client, clock, outbox):
    headers = sign_in(client, outbox)
    report(client, headers, 3)
    clock.advance(minutes=5)
    report(client, headers, 1)
    got = client.get("/v1/facilities/hitch-courts/activity").json()["reported"]
    assert got["reports"] == 1 and got["level"] == 1


def test_several_people_are_combined(client, clock, outbox):
    levels = [1, 3, 2]
    for i, lvl in enumerate(levels):
        clock.advance(seconds=90)
        h = sign_in(client, outbox, f"user{i}@ucla.edu")
        report(client, h, lvl)
    got = client.get("/v1/facilities/hitch-courts/activity").json()["reported"]
    assert got["reports"] == 3 and got["score"] == 2.0 and got["method"] == "median"


def test_old_reports_drop_out_of_the_window(client, clock, outbox):
    headers = sign_in(client, outbox)
    report(client, headers, 3)
    clock.advance(minutes=46)
    assert client.get("/v1/facilities/hitch-courts/activity").json()["reported"] is None


def test_reports_are_separate_per_facility(client, outbox):
    client.put("/v1/facilities/pools", json={"name": "Pools", "type": "pool"})
    headers = sign_in(client, outbox)
    report(client, headers, 3)
    assert client.get("/v1/facilities/pools/activity").json()["reported"] is None


# --- upcoming events ---------------------------------------------------------------


def test_upcoming_events_cross_days_and_skip_finished(client, clock):
    html = EVENTS.read_text(encoding="utf-8")
    client.put("/v1/facilities/wooden-center",
               json={"name": "JWC", "type": "gym", "venues": ["JWC"]})
    for day in ("2026-11-12", "2026-11-13"):
        client.post("/v1/ingest", json={"source_id": "s", "content": html, "event_date": day})
    # 18:00 UTC = 10:00 AM Pacific on the 12th: morning events are over
    got = client.get("/v1/events", params={"upcoming": "true", "facility_id": "wooden-center",
                                           "limit": 500}).json()
    assert got and all(e["end"] >= "2026-11-12T18:00:00Z" for e in got)
    assert {e["start"][:10] for e in got} >= {"2026-11-12", "2026-11-13"}
    assert [e["start"] for e in got] == sorted(e["start"] for e in got)
    assert len(client.get("/v1/events", params={"upcoming": "true", "limit": 3}).json()) == 3
    assert client.get("/v1/events", params={"limit": 0}).status_code == 422


# --- the dashboard is served ---------------------------------------------------------


def test_dashboard_is_served_and_api_wins(client):
    assert "<html" in client.get("/").text.lower() or "<!doctype" in client.get("/").text.lower()
    assert client.get("/v1/health").json() == {"status": "ok"}
    assert client.get("/docs").status_code == 200
