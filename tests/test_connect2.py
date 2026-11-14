from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rec_normalizers import ParseError, parse_connect2_counts

FIXTURE = Path(__file__).parent / "fixtures" / "wooden_counts.html"


@pytest.fixture(scope="module")
def counts():
    return parse_connect2_counts(FIXTURE.read_text(encoding="utf-8"))


def zone(counts, zone_id):
    return next(z for z in counts.zones if z.zone_id == zone_id)


def test_finds_all_eight_zones_in_page_order(counts):
    assert [z.name for z in counts.zones] == [
        "Collins Court",
        "Pardee Gym",
        "Cardio Zone",
        "Free Weight Zone",
        "Functional Training Zone",
        "Advanced Circuit Zone",
        "Novice Circuit Zone",
        "The Pit",
    ]
    assert counts.facility_name == "John Wooden Center - FITWELL"


def test_zone_ids_are_slugs(counts):
    assert zone(counts, "free-weight-zone").name == "Free Weight Zone"
    assert zone(counts, "the-pit").name == "The Pit"


def test_counts_and_open_status(counts):
    assert all(z.open for z in counts.zones)
    assert zone(counts, "collins-court").count == 35
    assert zone(counts, "free-weight-zone").count == 41


def test_percent_is_unrounded_value_from_data_attribute(counts):
    assert zone(counts, "free-weight-zone").percent_full == pytest.approx(
        63.07692307692307
    )
    assert zone(counts, "collins-court").percent_full == pytest.approx(
        1.9358407079646016
    )
    assert zone(counts, "cardio-zone").percent_full == 50


@pytest.mark.parametrize(
    "zone_id,capacity",
    [
        ("collins-court", 1808),
        ("pardee-gym", 50),
        ("cardio-zone", 60),
        ("free-weight-zone", 65),
        ("functional-training-zone", 40),
        ("advanced-circuit-zone", 45),
        ("novice-circuit-zone", 20),
        ("the-pit", 50),
    ],
)
def test_capacity_is_derived_from_count_and_percent(counts, zone_id, capacity):
    assert zone(counts, zone_id).capacity == capacity


@pytest.mark.parametrize(
    "zone_id,band",
    [
        ("collins-court", "low"),
        ("pardee-gym", "low"),
        ("cardio-zone", "low"),
        ("functional-training-zone", "low"),
        ("free-weight-zone", "medium"),
        ("advanced-circuit-zone", "medium"),
        ("novice-circuit-zone", "medium"),
        ("the-pit", "medium"),
    ],
)
def test_band_comes_from_bar_colour(counts, zone_id, band):
    assert zone(counts, zone_id).band == band


def test_updated_time_is_converted_from_pacific_to_utc(counts):
    # 11/11/2026 05:31 PM Pacific (PST, UTC-8) is 01:31 UTC the next day
    expected = datetime(2026, 11, 12, 1, 31, tzinfo=timezone.utc)
    assert counts.as_of == expected
    assert all(z.updated_at == expected for z in counts.zones)


def test_source_timezone_can_be_overridden():
    html = FIXTURE.read_text(encoding="utf-8")
    eastern = parse_connect2_counts(html, source_tz="America/New_York")
    # 05:31 PM Eastern (EST, UTC-5) is 22:31 UTC the same day
    assert eastern.as_of == datetime(2026, 11, 11, 22, 31, tzinfo=timezone.utc)


def test_to_official_matches_the_spec_shape_and_staleness(counts):
    fresh = counts.to_official(now=counts.as_of + timedelta(minutes=10))
    assert fresh["stale"] is False
    assert fresh["as_of"] == "2026-11-12T01:31:00Z"
    cardio = next(z for z in fresh["zones"] if z["zone_id"] == "cardio-zone")
    assert cardio == {
        "zone_id": "cardio-zone",
        "name": "Cardio Zone",
        "open": True,
        "count": 30,
        "percent_full": 50.0,
        "capacity": 60,
        "band": "low",
        "updated_at": "2026-11-12T01:31:00Z",
    }

    stale = counts.to_official(now=counts.as_of + timedelta(minutes=31))
    assert stale["stale"] is True


def test_closed_zone_has_no_percent_capacity_or_band():
    html = """
    <html><body><span id="facilityName">Test Facility</span>
    <div id="chartContainer"><div tabindex="0" class="barChart" style="width:90%;">
        Cardio Zone <br>
        <span style="color:#B30000">(Closed)</span><br>
        Last Count: 0 <br>
        Updated: 11/11/2026 05:31 PM
        <div class="barChart__row" data-value="0">
            <span class="barChart__value">NA</span>
            <span class="barChart__bar" style="background: rgb(239, 239, 239);">
                <span class="barChart__barFill" style="background: #FFF200; width: 0%;"></span>
            </span>
        </div>
    </div></div></body></html>
    """
    result = parse_connect2_counts(html)
    z = result.zones[0]
    assert z.open is False
    assert z.percent_full is None
    assert z.capacity is None
    assert z.band is None


def test_unknown_bar_colour_gives_no_band_not_a_guess():
    html = FIXTURE.read_text(encoding="utf-8").replace("#ffc90e", "#123456")
    result = parse_connect2_counts(html)
    assert zone(result, "the-pit").band is None
    assert zone(result, "the-pit").color == "#123456"


def test_unrendered_page_raises_a_clear_error():
    html = '<html><body><div id="chartContainer"></div></body></html>'
    with pytest.raises(ParseError, match="not rendered"):
        parse_connect2_counts(html)


def test_unrelated_page_raises():
    with pytest.raises(ParseError, match="not a Connect2"):
        parse_connect2_counts("<html><body><p>Hello</p></body></html>")


def test_zone_missing_a_count_raises():
    html = FIXTURE.read_text(encoding="utf-8").replace("Last Count: 35", "Count: 35")
    with pytest.raises(ParseError, match="Last Count"):
        parse_connect2_counts(html)
