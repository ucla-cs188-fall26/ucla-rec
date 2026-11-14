"""Scraper to API, over real HTTP: the CLI posts a page, the API stores and serves it."""

import json
import socket
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import uvicorn

from rec_api import create_app
from rec_api.config import Settings
from rec_scrapers.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "wooden_counts.html"
AS_OF = datetime(2026, 11, 12, 1, 31, tzinfo=timezone.utc)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "rec.db"
    app = create_app(
        Settings(database_url=f"sqlite:///{db}"),
        clock=lambda: AS_OF + timedelta(minutes=10),
    )
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "test server did not start"
    base = f"http://127.0.0.1:{port}"

    request = urllib.request.Request(
        f"{base}/v1/facilities/wooden-center",
        data=json.dumps({"name": "John Wooden Center", "type": "gym"}).encode(),
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(request).read()

    yield base
    server.should_exit = True
    thread.join(timeout=5)


def get_json(url):
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read())


def args_for(base, *extra):
    return ["--html-file", str(FIXTURE), "--post-to", base, "--facility-id", "wooden-center", *extra]


def test_scrape_post_and_read_back(api, capsys):
    assert main(args_for(api, "--source-id", "connect2-wooden")) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["api_response"]["status"] == "published"
    assert out["api_response"]["zones"] == 8
    assert out["api_response"]["source_id"] == "connect2-wooden"

    served = get_json(f"{api}/v1/facilities/wooden-center/activity")
    assert served["official"]["as_of"] == "2026-11-12T01:31:00Z"
    assert served["official"]["stale"] is False
    assert len(served["official"]["zones"]) == 8




def test_unknown_facility_is_reported(api, capsys):
    code = main(["--html-file", str(FIXTURE), "--post-to", api, "--facility-id", "nope"])
    assert code == 2
    assert "HTTP 404" in capsys.readouterr().err


def test_unrendered_page_is_refused_by_the_api(api, capsys, tmp_path):
    page = tmp_path / "empty.html"
    page.write_text('<html><body><div id="chartContainer"></div></body></html>', encoding="utf-8")
    code = main(["--html-file", str(page), "--post-to", api, "--facility-id", "wooden-center"])
    assert code == 2
    assert "not rendered" in capsys.readouterr().err


def test_unreachable_api_is_reported(capsys):
    assert main(args_for("http://127.0.0.1:1")) == 2
    assert "could not reach the API" in capsys.readouterr().err




def test_post_to_requires_a_facility_id(api):
    with pytest.raises(SystemExit) as info:
        main(["--html-file", str(FIXTURE), "--post-to", api])
    assert info.value.code == 2


def test_events_scrape_post_and_read_back(api, capsys):
    from rec_scrapers.events_cli import main as events_main

    page = Path(__file__).parent / "fixtures" / "browse_events_rows.html"
    put = urllib.request.Request(
        f"{api}/v1/facilities/wooden-center",
        data=json.dumps({"name": "John Wooden Center", "type": "gym", "venues": ["JWC"]}).encode(),
        method="PUT", headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(put).read()
    code = events_main(
        ["--html-file", str(page), "--date", "2026-11-12", "--post-to", api]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["api_response"]["events"] == 50

    events = get_json(f"{api}/v1/events?date=2026-11-12&facility_id=wooden-center")
    assert len(events) == 17 and all(e["venue"] == "JWC" for e in events)
