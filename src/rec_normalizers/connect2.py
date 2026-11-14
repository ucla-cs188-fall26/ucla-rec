"""Deterministic parser for Connect2Concepts "Live Facility Counts" pages.

Input is the *rendered* HTML of the widget page (what a browser shows after its
JavaScript has run). The raw server response has an empty chart container, so
an unrendered page raises ParseError instead of returning zero zones.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel

Band = Literal["low", "medium", "high"]

# Bar fill colours seen so far. Blue and yellow come from the Wooden sample.
# Red is the default high colour in the widget's own script; it has not been
# seen on UCLA's page yet. Unknown colours give band=None, never a guess.
BAND_BY_COLOR: dict[str, Band] = {
    "#2a5b84": "low",
    "#ffc90e": "medium",
    "#ed1c24": "high",
}

DEFAULT_SOURCE_TZ = "America/Los_Angeles"

_COUNT_RE = re.compile(r"Last Count:\s*(\d+)")
_UPDATED_RE = re.compile(r"Updated:\s*(\d{2}/\d{2}/\d{4} \d{2}:\d{2} [AP]M)")
_COLOR_RE = re.compile(r"background:\s*(#[0-9a-fA-F]{6})")


class ParseError(ValueError):
    """The page could not be turned into zone records."""


class Zone(BaseModel):
    zone_id: str
    name: str
    open: bool
    count: int
    percent_full: float | None
    capacity: int | None
    band: Band | None
    color: str | None
    updated_at: datetime  # UTC


class Connect2Counts(BaseModel):
    facility_name: str | None
    as_of: datetime  # newest zone update, UTC
    zones: list[Zone]

    def to_official(
        self, now: datetime | None = None, stale_after_minutes: int = 30
    ) -> dict:
        """Shape used by the `official` field of the activity endpoint."""
        now = now or datetime.now(timezone.utc)
        stale = now - self.as_of > timedelta(minutes=stale_after_minutes)
        return {
            "as_of": self.as_of.isoformat().replace("+00:00", "Z"),
            "stale": stale,
            "zones": [
                {
                    "zone_id": z.zone_id,
                    "name": z.name,
                    "open": z.open,
                    "count": z.count,
                    "percent_full": z.percent_full,
                    "capacity": z.capacity,
                    "band": z.band,
                    "updated_at": z.updated_at.isoformat().replace("+00:00", "Z"),
                }
                for z in self.zones
            ],
        }


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _parse_zone(block: Tag, source_tz: ZoneInfo) -> Zone:
    text_parts = [s.strip() for s in block.stripped_strings]
    if not text_parts:
        raise ParseError("empty zone block")
    name = text_parts[0]
    full_text = " ".join(text_parts)

    if "(Closed)" in full_text:
        is_open = False
    elif "(Open)" in full_text:
        is_open = True
    else:
        raise ParseError(f"zone {name!r} has no (Open) or (Closed) marker")

    count_match = _COUNT_RE.search(full_text)
    if not count_match:
        raise ParseError(f"zone {name!r} has no 'Last Count'")
    count = int(count_match.group(1))

    updated_match = _UPDATED_RE.search(full_text)
    if not updated_match:
        raise ParseError(f"zone {name!r} has no 'Updated' time")
    local = datetime.strptime(updated_match.group(1), "%m/%d/%Y %I:%M %p")
    updated_at = local.replace(tzinfo=source_tz).astimezone(timezone.utc)

    row = block.select_one(".barChart__row")
    fill = block.select_one(".barChart__barFill")

    percent: float | None = None
    if is_open and row is not None and row.get("data-value") not in (None, ""):
        percent = float(row["data-value"])

    color: str | None = None
    if fill is not None:
        color_match = _COLOR_RE.search(fill.get("style", ""))
        if color_match:
            color = color_match.group(1)
    band = BAND_BY_COLOR.get(color.lower()) if (color and is_open) else None

    capacity: int | None = None
    if percent and count > 0:
        capacity = round(count / (percent / 100))

    return Zone(
        zone_id=_slug(name),
        name=name,
        open=is_open,
        count=count,
        percent_full=percent,
        capacity=capacity,
        band=band,
        color=color,
        updated_at=updated_at,
    )


def parse_connect2_counts(
    html: str, source_tz: str = DEFAULT_SOURCE_TZ
) -> Connect2Counts:
    """Parse rendered Connect2 count HTML.

    `source_tz` is the time zone the page printed its "Updated" times in. The
    page uses the viewer's browser zone, so the scraper's browser should be set
    to America/Los_Angeles.
    """
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#chartContainer")
    if container is None:
        raise ParseError("no #chartContainer: this is not a Connect2 counts page")

    blocks = container.select("div.barChart")
    if not blocks:
        raise ParseError(
            "chart container is empty: the page was not rendered. "
            "Render it in a headless browser or use the JSON endpoint it loads."
        )

    tz = ZoneInfo(source_tz)
    zones = [_parse_zone(b, tz) for b in blocks]

    name_el = soup.select_one("#facilityName")
    facility_name = name_el.get_text(strip=True) if name_el else None

    return Connect2Counts(
        facility_name=facility_name,
        as_of=max(z.updated_at for z in zones),
        zones=zones,
    )
