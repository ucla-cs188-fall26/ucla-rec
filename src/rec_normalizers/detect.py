"""Work out which kind of UCLA Rec page a piece of HTML is."""

from __future__ import annotations

from typing import Literal

from bs4 import BeautifulSoup

from .pool_schedule import is_pool_schedule

PageType = Literal["connect2_counts", "events", "pool_schedule"]


def detect_page_type(html: str) -> PageType | None:
    """Connect2 counts page, Browse Events grid, or None if it is neither."""
    if is_pool_schedule(html):
        return "pool_schedule"
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("#chartContainer") is not None:
        return "connect2_counts"
    if soup.select_one("tbody.event-grid, .dx-datagrid-rowsview, .dx-datagrid") is not None:
        return "events"
    return None
