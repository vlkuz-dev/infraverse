"""Pagination helpers for web routes."""

DEFAULT_PER_PAGE = 50


def clamp_page(page: int, per_page: int, total_count: int) -> int:
    """Clamp page number to valid range given total count."""
    total_pages = max(1, -(-total_count // per_page))
    return max(1, min(page, total_pages))


def _page_range(current: int, total: int, window: int = 2) -> list[int | None]:
    """Build page number list with ellipsis gaps (None = ellipsis)."""
    if total <= 7:
        return list(range(1, total + 1))

    pages: set[int] = {1, total}
    for p in range(max(1, current - window), min(total, current + window) + 1):
        pages.add(p)

    result: list[int | None] = []
    for p in sorted(pages):
        if result and isinstance(result[-1], int) and p - result[-1] > 1:
            result.append(None)
        result.append(p)
    return result


def _build_qs(params: dict) -> str:
    """Build a query string from param dict, skipping None/empty values."""
    parts = []
    for k, v in params.items():
        if v is not None and str(v) != "":
            parts.append(f"{k}={v}")
    return "&".join(parts)


def build_pagination(
    page: int,
    per_page: int,
    total_count: int,
    base_url: str,
    query_params: dict,
    htmx_base_url: str | None = None,
    htmx_target: str | None = None,
) -> dict | None:
    """Build pagination context dict for templates.

    Args:
        page: Current page number (1-based).
        per_page: Items per page.
        total_count: Total number of items.
        base_url: Base URL path for page links (e.g. "/vms").
        query_params: Current query params (page will be replaced).
        htmx_base_url: Optional HTMX base URL for partial updates.
        htmx_target: Optional HTMX target selector.

    Returns:
        Pagination context dict, or None if only one page.
    """
    total_pages = max(1, -(-total_count // per_page))
    page = max(1, min(page, total_pages))

    if total_pages <= 1:
        return None

    # Base params without page
    base_params = {k: v for k, v in query_params.items() if k != "page"}
    if per_page != DEFAULT_PER_PAGE:
        base_params["per_page"] = per_page

    def make_url(p: int, base: str) -> str:
        qs = _build_qs({**base_params, "page": p})
        return f"{base}?{qs}" if qs else base

    pages = _page_range(page, total_pages)
    page_nums = [p for p in pages if p is not None]

    return {
        "page": page,
        "per_page": per_page,
        "total_count": total_count,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "showing_start": (page - 1) * per_page + 1 if total_count > 0 else 0,
        "showing_end": min(page * per_page, total_count),
        "page_range": pages,
        "page_urls": {p: make_url(p, base_url) for p in page_nums},
        "prev_url": make_url(page - 1, base_url) if page > 1 else "#",
        "next_url": make_url(page + 1, base_url) if page < total_pages else "#",
        "htmx_urls": (
            {p: make_url(p, htmx_base_url) for p in page_nums}
            if htmx_base_url
            else None
        ),
        "htmx_prev_url": (
            make_url(page - 1, htmx_base_url)
            if htmx_base_url and page > 1
            else None
        ),
        "htmx_next_url": (
            make_url(page + 1, htmx_base_url)
            if htmx_base_url and page < total_pages
            else None
        ),
        "htmx_target": htmx_target,
    }
