"""Read the UCLA Rec pool calendar (a PDF printed from a spreadsheet).

The PDF is a month grid: each day cell holds lines such as

    PP - 11am-8pm                    a pool and its open hours
      Open Rec Diving 3p-5p          an activity at the pool above it
    FP - 6am - 10am, 12pm-6pm        several ranges in one day
    SAC - CLOSED (Deck Maintenance)  a closure, with a reason
    North Pool - TBD                 not yet announced

A banner cell such as "THANKSGIVING HOLIDAY ALL POOLS CLOSED" closes every pool.

The scraper turns the PDF into positioned words (see `rec_scrapers.pdf`) and the
API reads those. Working from word positions, not the PDF's text order, is what
keeps a line from one day's cell out of the next day's.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .connect2 import DEFAULT_SOURCE_TZ, ParseError
from .vems_events import Event

FORMAT = "pdf_words"
_MONTHS = ["january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december"]
_WEEKDAYS = {"MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"}

_T = r"(\d{1,2})(?::(\d{2}))?\s*([ap])m?"
_RANGE = re.compile(rf"{_T}\s*-\s*{_T}\s*$", re.I)
_RANGE_ANYWHERE = re.compile(rf"{_T}\s*-\s*{_T}", re.I)
_POOL_LINE = re.compile(r"^(PP|FP|SAC|[A-Za-z]+ Pool)\s*-\s*(.+)$")
_LEGEND = re.compile(r"^([A-Z]{2,4})\s*-\s*(.+\bPool)$")
_DAY_TOKEN = re.compile(r"^\d{1,2}$")


def is_pool_schedule(content: str) -> bool:
    return content.lstrip().startswith("{") and f'"{FORMAT}"' in content[:200]


# --- words -> lines ----------------------------------------------------------

def _lines(words: list[dict], tol: float = 2.5) -> list[list[dict]]:
    """Group words into lines by their top edge; each line is left to right."""
    out: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if out and abs(out[-1][0]["top"] - w["top"]) <= tol:
            out[-1].append(w)
        else:
            out.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in out]


def _text(line: list[dict]) -> str:
    return " ".join(w["text"] for w in line)


# --- the page ------------------------------------------------------------------

def _title(words: list[dict], header_top: float) -> tuple[int, int]:
    """First month and year in the title, e.g. 'November-December 2026'."""
    above = " ".join(w["text"] for w in sorted(words, key=lambda w: (w["top"], w["x0"]))
                     if w["top"] < header_top).lower()
    month = next((m for m in sorted(((above.find(n), i + 1) for i, n in enumerate(_MONTHS)
                                     if n in above))), None)
    year = re.search(r"\b(20\d\d)\b", above)
    if not month or not year:
        raise ParseError("could not find the month and year in the calendar title")
    return month[1], int(year.group(1))


def _legend(words: list[dict], header_top: float) -> dict[str, str]:
    """'PP - Park Pool' -> {'PP': 'Park Pool'}"""
    legend: dict[str, str] = {}
    left = [w for w in words if w["top"] < header_top and w["x0"] < 200]
    for line in _lines(left):
        m = _LEGEND.match(_text(line))
        if m:
            legend[m.group(1)] = m.group(2)
    return legend


def _clock(h: str, m: str | None, ap: str) -> time:
    hour = int(h) % 12 + (12 if ap.lower() == "p" else 0)
    return time(hour, int(m or 0))


def _ranges(text: str) -> list[tuple[time, time]] | None:
    """'6am - 10am, 12pm-6pm' -> two ranges; None if any part is not a range."""
    out = []
    for part in text.split(","):
        m = _RANGE.fullmatch(part.strip())
        if not m:
            return None
        g = m.groups()
        out.append((_clock(g[0], g[1], g[2]), _clock(g[3], g[4], g[5])))
    return out


def _page_events(words: list[dict], tz: ZoneInfo) -> tuple[list[Event], list[str]]:
    header = [w for w in words if w["text"].upper() in _WEEKDAYS]
    if len({w["text"].upper() for w in header}) < 7:
        raise ParseError("no Monday to Sunday header found")
    header_top = min(w["top"] for w in header)
    header_bottom = max(w["bottom"] for w in header)
    start_month, year = _title(words, header_top)
    legend = _legend(words, header_top)

    body = [w for w in words if w["top"] > header_bottom]
    # Drop the full-width banner ("UCLA CAMPUS CLOSURE - DECEMBER 24 - JANUARY 2"):
    # the cells below it already say CLOSED.
    banner_tops = [w["top"] for w in body if w["text"].upper() == "CAMPUS"]
    body = [w for w in body if not any(abs(w["top"] - t) < 4 for t in banner_tops)]
    foot = [w["top"] for w in body if w["text"].startswith("*")]
    page_end = min(foot) if foot else float("inf")

    # Day numbers: right-aligned, one per cell, in a row across the page.
    nums = [w for w in body if _DAY_TOKEN.match(w["text"]) and w["top"] < page_end]
    rows = [r for r in _lines(nums) if len(r) >= 4]
    if not rows:
        raise ParseError("could not find the day numbers in the calendar")
    full = next((r for r in rows if len(r) == 7), None)
    if full is None:
        raise ParseError("could not find a week with all seven day numbers")
    # Column borders sit just past each number's right edge.
    right = [w["x1"] + 1.5 for w in full]

    def column(x: float) -> int:
        # A word belongs to the column whose right border it starts before. Text
        # never starts left of the table or right of Sunday's border by design.
        for i in range(6):
            if x < right[i] + 0.5:
                return i
        return 6

    row_tops = [r[0]["top"] for r in rows]
    bounds = row_tops[1:] + [page_end]
    first = rows[0][0]
    first_col = column(first["x0"])
    first_date = date(year, start_month, int(first["text"]))

    events: list[Event] = []
    skipped: list[str] = []
    pool_codes = list(legend)

    for week, (top, end) in enumerate(zip(row_tops, bounds)):
        # Words of this week's cells (below the number line, above the next week).
        cells: dict[int, list[dict]] = {}
        number_line = [w for w in body if abs(w["top"] - top) < 3]
        for w in body:
            if not (top + 3 < w["top"] < end - 1):
                continue
            cells.setdefault(column(w["x0"]), []).append(w)

        for c in range(7):
            day = first_date + timedelta(days=week * 7 + c - first_col)
            # The number printed in the cell must agree with the date we counted to.
            printed = [w for w in number_line if column(w["x0"]) == c]
            digits = re.findall(r"\d+", " ".join(w["text"] for w in printed))
            if digits and int(digits[0]) != day.day:
                raise ParseError(
                    f"day numbers do not line up: expected {day.day} but the calendar shows {digits[0]}"
                )
            lines = [_text(line) for line in _lines(cells.get(c, []))]
            _cell_events(lines, day, tz, legend, pool_codes, events, skipped)
    return events, skipped


def _local(day: date, t: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, t, tzinfo=tz).astimezone(timezone.utc)


def _all_day(name: str, kind: str, venue: str | None, day: date, tz: ZoneInfo,
             code: str | None = None) -> Event:
    start = datetime.combine(day, time(0, 0), tzinfo=tz)
    return Event(
        name=name, kind=kind, all_day=True, venue=venue, location=venue, space=code,
        start=start.astimezone(timezone.utc),
        end=(start + timedelta(days=1)).astimezone(timezone.utc),
    )


def _cell_events(lines, day, tz, legend, pool_codes, out, skipped) -> None:
    if not lines:
        return
    joined = " ".join(lines).upper()
    # One banner for the whole cell: every pool is closed.
    if "ALL POOLS" in joined and "CLOSED" in joined and not _POOL_LINE.match(lines[0]):
        name = " ".join(lines).title()
        for code in pool_codes:
            out.append(_all_day(name, "closed", legend[code], day, tz, code))
        return

    venue: str | None = None
    code: str | None = None  # the short label printed on the calendar, e.g. "PP"
    for line in lines:
        m = _POOL_LINE.match(line)
        if m:
            code, rest = m.group(1), m.group(2).strip()
            venue = legend.get(code, code)
            upper = rest.upper()
            if upper.startswith("CLOSED"):
                reason = re.search(r"\((.+)\)", rest)
                label = f"Closed ({reason.group(1)})" if reason else "Closed"
                out.append(_all_day(label, "closed", venue, day, tz, code))
            elif upper == "TBD":
                out.append(_all_day("Hours not yet posted", "tbd", venue, day, tz, code))
            else:
                spans = _ranges(rest)
                if spans is None:
                    skipped.append(f"{day}: {line}")
                    continue
                for s, e in spans:
                    out.append(Event(
                        name="Open", kind="pool_hours", venue=venue, location=venue, space=code,
                        start=_local(day, s, tz), end=_local(day, e, tz),
                    ))
            continue
        m = _RANGE.search(line)
        if m and line[: m.start()].strip():
            g = m.groups()
            out.append(Event(
                name=line[: m.start()].strip(), kind="pool_activity", venue=venue, location=venue, space=code,
                start=_local(day, _clock(*g[0:3]), tz), end=_local(day, _clock(*g[3:6]), tz),
            ))
            continue
        skipped.append(f"{day}: {line}")


# --- entry point -----------------------------------------------------------------

def parse_pool_schedule(
    content: str, source_tz: str = DEFAULT_SOURCE_TZ
) -> tuple[list[Event], list[str]]:
    """Positioned PDF words (JSON) -> events, plus any lines that were not understood."""
    try:
        doc = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ParseError(f"not valid JSON: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ParseError("this is not a pool calendar")
    tz = ZoneInfo(source_tz)
    events: list[Event] = []
    skipped: list[str] = []
    problems: list[str] = []
    for n, page in enumerate(doc.get("pages", []), start=1):
        try:
            found, notes = _page_events(page["words"], tz)
        except ParseError as exc:
            problems.append(f"page {n}: {exc}")
            continue
        events += found
        skipped += notes
    if not events:
        raise ParseError("; ".join(problems) or "no calendar found in the PDF")
    return events, skipped
