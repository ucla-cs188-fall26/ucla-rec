"""Deterministic parser for the UCLA Rec "Browse Events" grid.

Input is the *rendered* HTML of https://reserve.recreation.ucla.edu/BrowseEvents.aspx
(or just the grid's markup). Each row is one booking: start time, end time,
event name and location. Rows carry no date, so the caller supplies the date
the page was showing.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel

from .connect2 import DEFAULT_SOURCE_TZ, ParseError

EventKind = Literal[
    "open_recreation", "class", "club_sport", "athletics", "maintenance", "other",
    # from the pool calendar:
    "pool_hours", "pool_activity", "closed", "tbd",
]
EVENT_KINDS: tuple[str, ...] = (
    "open_recreation", "class", "club_sport", "athletics", "maintenance", "other",
    "pool_hours", "pool_activity", "closed", "tbd",
)

# First match wins. Matched against the lower-cased event name.
_KIND_RULES: list[tuple[EventKind, re.Pattern[str]]] = [
    ("maintenance", re.compile(r"custodial|seismic|improvement project|maintenance|repair")),
    ("open_recreation", re.compile(r"^open rec|^lap swim|^open swim|^open gym")),
    ("class", re.compile(r"\bclass(es)?\b|-class-|\bbhip")),
    ("club_sport", re.compile(r"\bclub\b|^mrugby|^wrugby|masters swimming")),
    ("athletics", re.compile(r"^dia\b|^dia-|^ucla (women|men)|athletic performance|cheer squad|dance team")),
]

_TIME_FORMAT = "%I:%M %p"


class Event(BaseModel):
    name: str
    start: datetime  # timezone-aware UTC
    end: datetime
    all_day: bool = False
    cancelled: bool = False
    location: str | None = None  # as printed, e.g. "JWC - Yates Gym"
    venue: str | None = None  # text before the first " - ", e.g. "JWC"
    space: str | None = None  # the rest, e.g. "Yates Gym"
    kind: EventKind = "other"


def classify(name: str) -> EventKind:
    lowered = name.lower().strip()
    for kind, pattern in _KIND_RULES:
        if pattern.search(lowered):
            return kind
    return "other"


def split_location(location: str | None) -> tuple[str | None, str | None]:
    if not location:
        return None, None
    head, sep, tail = location.partition(" - ")
    return head.strip() or None, (tail.strip() or None) if sep else None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _cell_time(row: Tag, label: str) -> time | None:
    cell = row.find("td", attrs={"aria-label": re.compile(rf"^{label} ")})
    if cell is None:
        return None
    try:
        return datetime.strptime(_clean(cell.get_text()), _TIME_FORMAT).time()
    except ValueError as exc:
        raise ParseError(f"unreadable {label.lower()}: {cell.get_text()!r}") from exc


def parse_vems_events(
    html: str, event_date: date, source_tz: str = DEFAULT_SOURCE_TZ
) -> list[Event]:
    """Parse the events grid for `event_date`. Returns events sorted by start.

    An empty list means the grid was present with no rows. A page with no grid
    at all raises ParseError, so a wrong or unrendered page is never mistaken
    for "no events today".
    """
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("tbody.event-grid, .dx-datagrid-rowsview, .dx-datagrid") is None:
        raise ParseError(
            "no events grid found: is this the rendered Browse Events page? "
            "Render it in a browser first."
        )

    zone = ZoneInfo(source_tz)
    events: list[Event] = []

    for row in soup.select("tbody.event-grid tr"):
        classes = row.get("class") or []
        if "evenRows" not in classes and "oddRows" not in classes:
            continue  # the grid's hidden spacer row

        links = row.find_all("a")
        name_link = next((a for a in links if not a.get("title")), None)
        place_link = next((a for a in links if a.get("title")), None)
        if name_link is None:
            raise ParseError("an event row has no name")
        name = _clean(name_link.get_text())
        location = _clean(place_link.get_text()) if place_link else None

        start_t, end_t = _cell_time(row, "Start Time"), _cell_time(row, "End Time")
        all_day = start_t is None
        if all_day:
            start_local = datetime.combine(event_date, time(0, 0), tzinfo=zone)
            end_local = start_local + timedelta(days=1)
        else:
            start_local = datetime.combine(event_date, start_t, tzinfo=zone)
            end_local = datetime.combine(event_date, end_t or start_t, tzinfo=zone)
            if end_local < start_local:  # runs past midnight
                end_local += timedelta(days=1)

        cancelled = "row-cancelled" in classes or any(
            "grey-text" in (a.get("class") or []) for a in (name_link,)
        )
        venue, space = split_location(location)
        events.append(
            Event(
                name=name,
                start=start_local.astimezone(timezone.utc),
                end=end_local.astimezone(timezone.utc),
                all_day=all_day,
                cancelled=cancelled,
                location=location,
                venue=venue,
                space=space,
                kind=classify(name),
            )
        )

    events.sort(key=lambda e: (e.start, e.name, e.location or ""))
    return events
