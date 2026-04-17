"""Pagination metadata helpers.

python-gitlab returns list results as ``RESTObjectList`` which carries pagination
hints in response headers (``X-Total``, ``X-Total-Pages``, ``X-Next-Page``, …).
This module extracts that info into a uniform ``pagination`` block so that list
tools can expose ``has_more`` / ``next_page`` / ``total`` to the agent.
"""

from __future__ import annotations

from typing import Any


def extract(result: Any) -> dict[str, Any]:
    """Extract pagination metadata from a python-gitlab list result.

    Works for both the paginated RESTObjectList (from ``list(get_all=False)``) and
    plain Python lists (from ``get_all=True``) — in the latter case only ``total``
    is filled and ``has_more`` is ``False``.
    """
    if isinstance(result, list):
        return {
            "page": 1,
            "per_page": len(result),
            "total": len(result),
            "total_pages": 1,
            "next_page": None,
            "has_more": False,
        }

    next_page = getattr(result, "next_page", None)
    return {
        "page": getattr(result, "current_page", None),
        "per_page": getattr(result, "per_page", None),
        "total": getattr(result, "total", None),
        "total_pages": getattr(result, "total_pages", None),
        "next_page": next_page,
        "has_more": bool(next_page),
    }


def footer_md(pg: dict[str, Any]) -> str:
    """Format a single-line markdown footer summarising the pagination state."""
    page = pg.get("page") or 1
    per_page = pg.get("per_page") or "?"
    total = pg.get("total")
    total_pages = pg.get("total_pages")
    if not pg.get("has_more"):
        if total is None:
            return f"_Page {page} · {per_page} per page · last page._"
        return f"_Page {page} of {total_pages or page} · {total} total · last page._"
    return (
        f"_Page {page} of {total_pages or '?'} · {total or '?'} total · "
        f"call again with page={pg.get('next_page')} for the next page._"
    )
