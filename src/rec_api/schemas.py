from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field

FacilityType = Literal["gym", "fitness_center", "pool", "court", "field", "other"]

# Stable slug, for example "wooden-center".
FACILITY_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,78}$"


class FacilityIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: FacilityType = "other"
    # Venue codes that start this facility's event locations ("JWC" for
    # "JWC - Yates Gym"). Events at these venues are linked to the facility.
    venues: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=50
    )


class FacilityOut(BaseModel):
    id: str
    name: str
    type: FacilityType | str
    venues: list[str] = []
    updated_at: str


class IngestActivityIn(BaseModel):
    facility_id: str = Field(pattern=FACILITY_ID_PATTERN)
    source_id: str = Field(min_length=1, max_length=120)
    content_type: Literal["text/html"] = "text/html"
    content: str = Field(min_length=1, max_length=2_000_000)
    # Zone the page printed its "Updated" times in.
    source_timezone: str = "America/Los_Angeles"


class IngestActivityOut(BaseModel):
    status: Literal["published"]
    facility_id: str
    source_id: str
    zones: int
    as_of: str


class ActivityOut(BaseModel):
    facility_id: str
    official: dict | None
    reported: dict | None = None


class IngestEventsIn(BaseModel):
    source_id: str = Field(min_length=1, max_length=120)
    content_type: Literal["text/html"] = "text/html"
    content: str = Field(min_length=1, max_length=5_000_000)
    # The date the page was showing. The grid's rows carry only times.
    event_date: date
    source_timezone: str = "America/Los_Angeles"


class IngestEventsOut(BaseModel):
    status: Literal["published"]
    source_id: str
    event_date: str
    events: int
    replaced: int  # events from an earlier scrape of the same source and date
    by_kind: dict[str, int]


class EventOut(BaseModel):
    id: int
    name: str
    kind: str
    status: Literal["scheduled", "cancelled"]
    start: str
    end: str
    all_day: bool
    location: str | None
    venue: str | None
    space: str | None
    facility_id: str | None
    source_id: str


class IngestIn(BaseModel):
    """One endpoint for every source. The API works out what the page is."""

    source_id: str = Field(min_length=1, max_length=120)
    # A pool calendar PDF arrives as positioned words in JSON; everything else is HTML.
    content_type: Literal["text/html", "application/json"] = "text/html"
    content: str = Field(min_length=1, max_length=5_000_000)
    # Required for a Connect2 counts page. For an events page it is optional:
    # give it to put every event on that facility, leave it out to split the
    # events across facilities by venue.
    facility_id: str | None = Field(default=None, pattern=FACILITY_ID_PATTERN)
    # Events pages only: the day the page showed (default: today in the source zone).
    event_date: date | None = None
    source_timezone: str = "America/Los_Angeles"


class IngestOut(BaseModel):
    status: Literal["published"]
    type: Literal["connect2_counts", "events", "pool_schedule"]
    source_id: str
    facility_id: str | None = None
    # pool_schedule: the days the calendar covers, and lines that were not understood
    last_date: str | None = None
    skipped: list[str] | None = None
    # connect2_counts
    zones: int | None = None
    as_of: str | None = None
    # events
    event_date: str | None = None
    events: int | None = None
    replaced: int | None = None
    by_kind: dict[str, int] | None = None
    by_facility: dict[str, int] | None = None  # events per facility id ("unassigned" if none)


class CodeRequestIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class CodeRequestOut(BaseModel):
    status: Literal["sent"]
    expires_in_seconds: int
    dev_code: str | None = None  # only when the server runs with REC_SHOW_CODES


class VerifyIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=4, max_length=12)


class VerifyOut(BaseModel):
    token: str
    expires_at: str


class ReportIn(BaseModel):
    level: int = Field(ge=1, le=3, description="1 Quiet, 2 Moderate, 3 Busy")


class ReportOut(BaseModel):
    status: Literal["recorded"]
    facility_id: str
    level: int
    reported: dict | None
