"""The one runner: a config file drives every source into the one ingest endpoint."""

import json
from pathlib import Path

import pytest

from rec_scrapers.run import ConfigError, load_config, main

from test_pipeline import api, get_json  # noqa: F401  (the real-server fixture)

FIX = Path(__file__).parent / "fixtures"


def write_config(tmp_path, **overrides):
    (tmp_path / "counts.html").write_text((FIX / "wooden_counts.html").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "events.html").write_text((FIX / "browse_events_rows.html").read_text(encoding="utf-8"), encoding="utf-8")
    config = {
        "facilities": [
            {"id": "wooden-center", "name": "John Wooden Center", "type": "gym", "venues": ["JWC"],
             "sources": [{"id": "connect2-wooden", "type": "connect2_counts", "html_file": "counts.html"}]},
            {"id": "sunset-rec", "name": "Sunset Rec", "type": "gym", "venues": ["SCRC"], "sources": []},
        ],
        "sources": [{"id": "ucla-reserve-events", "type": "events", "html_file": "events.html"}],
        **overrides,
    }
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(config))
    return path


def test_runs_every_source_through_the_one_endpoint(api, tmp_path, capsys):
    cfg = write_config(tmp_path)
    code = main(["--config", str(cfg), "--api", api, "--date", "2026-11-12"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    by_id = {r["source"]: r for r in out["results"]}
    assert by_id["connect2-wooden"]["response"]["type"] == "connect2_counts"
    assert by_id["connect2-wooden"]["response"]["zones"] == 8
    assert by_id["ucla-reserve-events"]["response"]["by_facility"]["wooden-center"] == 17

    assert get_json(f"{api}/v1/facilities/wooden-center/activity")["official"] is not None
    assert len(get_json(f"{api}/v1/events?date=2026-11-12&facility_id=wooden-center")) == 17
    assert get_json(f"{api}/v1/facilities/sunset-rec")["venues"] == ["SCRC"]


def test_only_runs_the_named_source(api, tmp_path, capsys):
    cfg = write_config(tmp_path)
    assert main(["--config", str(cfg), "--api", api, "--only", "connect2-wooden"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["source"] for r in out["results"]] == ["connect2-wooden"]


def test_one_failure_does_not_stop_the_rest(api, tmp_path, capsys):
    cfg = write_config(tmp_path)
    (tmp_path / "counts.html").write_text("<html><body>Sign in</body></html>")
    code = main(["--config", str(cfg), "--api", api, "--date", "2026-11-12"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    by_id = {r["source"]: r for r in out["results"]}
    assert not by_id["connect2-wooden"]["ok"] and "expected a connect2_counts page" in by_id["connect2-wooden"]["error"]
    assert by_id["ucla-reserve-events"]["ok"]


def test_a_page_of_the_wrong_type_is_caught(api, tmp_path, capsys):
    cfg = write_config(tmp_path)
    (tmp_path / "counts.html").write_text((FIX / "browse_events_rows.html").read_text(encoding="utf-8"))
    assert main(["--config", str(cfg), "--api", api, "--only", "connect2-wooden"]) == 1
    assert "expected a connect2_counts page but got events" in capsys.readouterr().out


def test_missing_url_variable_is_reported(api, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CONNECT2_X_URL", raising=False)
    cfg = write_config(tmp_path, sources=[{"id": "x", "type": "events", "url_env": "CONNECT2_X_URL"}])
    assert main(["--config", str(cfg), "--api", api, "--only", "x"]) == 1
    assert "CONNECT2_X_URL is not set" in capsys.readouterr().out


def test_unreachable_api_is_reported(tmp_path, capsys):
    cfg = write_config(tmp_path)
    assert main(["--config", str(cfg), "--api", "http://127.0.0.1:9"]) == 1
    assert "could not reach the API" in capsys.readouterr().out


@pytest.mark.parametrize("bad, message", [
    ({"sources": [{"id": "a", "type": "nope", "url": "x"}]}, "type must be one of"),
    ({"sources": [{"id": "a", "type": "events"}]}, "give a url"),
    ({"sources": [{"type": "events", "url": "x"}]}, "needs an id"),
    ({"sources": [{"id": "a", "type": "connect2_counts", "url": "x"}], "facilities": []}, "must sit under a facility"),
    ({"sources": [{"id": "a", "type": "events", "url": "x"}, {"id": "a", "type": "events", "url": "x"}]}, "duplicate source id"),
    ({"facilities": [{"id": "f"}]}, "id and a name"),
])
def test_config_problems(tmp_path, bad, message):
    path = tmp_path / "c.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_unknown_source_and_bad_date_and_missing_file(tmp_path, capsys):
    cfg = write_config(tmp_path)
    assert main(["--config", str(cfg), "--only", "nope"]) == 2
    assert main(["--config", str(cfg), "--date", "12/11/2026"]) == 2
    assert main(["--config", str(tmp_path / "missing.json")]) == 2


def test_example_config_is_valid():
    config = load_config(Path(__file__).parent.parent / "sources.example.json")
    assert {s["id"] for s in config["sources"]} == {"connect2-wooden", "connect2-803", "ucla-reserve-events", "pool-calendar"}
