"""Community-reported crowd level: how reports are combined."""

from __future__ import annotations

import hashlib
import hmac
import statistics
from datetime import datetime, timezone

LABELS = {1: "Quiet", 2: "Moderate", 3: "Busy"}
TRIM_FROM = 5  # with this many reports or more, drop the lowest and highest


def digest(secret: str, value: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def combine(levels: list[int]) -> tuple[float, str]:
    """Middle value of the reports. With 5 or more, the lowest and highest are
    dropped first so one outlier cannot move the result."""
    ordered = sorted(levels)
    method = "median"
    if len(ordered) >= TRIM_FROM:
        ordered = ordered[1:-1]
        method = "trimmed_median"
    return float(statistics.median(ordered)), method


def summarize(
    latest_by_user: list[tuple[int, datetime]], window_minutes: int
) -> dict | None:
    """`latest_by_user`: each person's newest (level, time) inside the window."""
    if not latest_by_user:
        return None
    score, method = combine([lvl for lvl, _ in latest_by_user])
    level = int(score + 0.5)  # halves round up: 1.5 -> Moderate
    newest = max(t for _, t in latest_by_user)
    return {
        "level": level,
        "label": LABELS[level],
        "score": score,
        "reports": len(latest_by_user),
        "window_minutes": window_minutes,
        "method": method,
        "as_of": newest.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
