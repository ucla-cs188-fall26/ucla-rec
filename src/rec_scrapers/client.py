"""Send a scraped page to the Rec API's ingest endpoint (standard library only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class PostError(RuntimeError):
    """The API could not be reached or refused the page."""


def post_activity(
    base_url: str,
    *,
    facility_id: str,
    source_id: str,
    content: str,
    source_timezone: str,
    timeout: float = 30.0,
) -> dict:
    return _post(
        base_url,
        "/v1/ingest/activity",
        {
            "facility_id": facility_id,
            "source_id": source_id,
            "content_type": "text/html",
            "content": content,
            "source_timezone": source_timezone,
        },
        timeout,
    )


def post_events(
    base_url: str,
    *,
    source_id: str,
    content: str,
    event_date: str,
    source_timezone: str,
    timeout: float = 60.0,
) -> dict:
    return _post(
        base_url,
        "/v1/ingest/events",
        {
            "source_id": source_id,
            "content_type": "text/html",
            "content": content,
            "event_date": event_date,
            "source_timezone": source_timezone,
        },
        timeout,
    )


def put_facility(
    base_url: str, facility_id: str, *, name: str, type: str = "other",
    venues: list[str] | None = None, timeout: float = 30.0,
) -> dict:
    return _post(
        base_url, f"/v1/facilities/{facility_id}",
        {"name": name, "type": type, "venues": venues or []}, timeout, method="PUT",
    )


def post_ingest(
    base_url: str,
    *,
    source_id: str,
    content: str,
    facility_id: str | None = None,
    event_date: str | None = None,
    source_timezone: str = "America/Los_Angeles",
    timeout: float = 60.0,
) -> dict:
    """The one ingest call: the API works out what kind of page this is."""
    payload = {
        "source_id": source_id, "content": content,
        "content_type": "application/json" if content.lstrip().startswith("{") else "text/html",
        "source_timezone": source_timezone,
    }
    if facility_id:
        payload["facility_id"] = facility_id
    if event_date:
        payload["event_date"] = event_date
    return _post(base_url, "/v1/ingest", payload, timeout)


def _post(base_url: str, path: str, payload: dict, timeout: float, method: str = "POST") -> dict:
    base = base_url.rstrip("/")
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8", "replace"))["error"]["message"]
        except Exception:
            pass
        raise PostError(f"the API refused the page (HTTP {exc.code}): {detail}".rstrip(": ")) from exc
    except urllib.error.URLError as exc:
        raise PostError(f"could not reach the API at {base}: {exc.reason}") from exc
