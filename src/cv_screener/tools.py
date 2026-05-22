"""Tools the specialist agents can call.

Each function below has typed arguments + a docstring so pydantic-ai can
auto-generate the JSON Schema and expose it to the LLM. The agent decides
when to call which tool; we don't drive that from Python.
"""

from __future__ import annotations

import os
from datetime import date

import httpx

_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


async def web_search(query: str, max_results: int = 3) -> str:
    """Search the public web. Use this when you encounter an unknown
    technology, company, university, or claim that you cannot verify from
    the CV / JD alone. Returns a short list of titles + URLs + snippets.

    Examples of good queries:
      - "Tekton CI/CD project description"
      - "Ledgerly fintech company"
      - "University of Waterloo computer science ranking"

    Args:
        query: A focused search query (3-8 words works best).
        max_results: How many results to retrieve. 1-5. Defaults to 3.
    """
    key = os.getenv("BRAVE_API_KEY")
    if not key:
        return "Search unavailable: BRAVE_API_KEY is not set. Proceed without web evidence."
    count = max(1, min(max_results, 5))
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                _BRAVE_URL,
                params={"q": query, "count": count, "result_filter": "web"},
                headers={
                    "X-Subscription-Token": key,
                    "Accept": "application/json",
                },
            )
        if r.status_code != 200:
            return f"Search error: HTTP {r.status_code} — {r.text[:200]}"
        data = r.json()
        results = (data.get("web") or {}).get("results") or []
        if not results:
            return f"No results for: {query}"
        lines = []
        for i, item in enumerate(results[:count], 1):
            title = item.get("title", "(no title)")
            url = item.get("url", "")
            desc = item.get("description", "")
            lines.append(f"[{i}] {title}\n    {url}\n    {desc}")
        return "\n\n".join(lines)
    except httpx.TimeoutException:
        return "Search error: timeout. Proceed without web evidence."
    except Exception as exc:  # noqa: BLE001
        return f"Search error: {type(exc).__name__}: {exc}"


def compute_years_between(start: str, end: str) -> float:
    """Compute the number of years between two dates. Useful for tenure and
    gap calculations where exact arithmetic matters more than the model's
    estimate.

    Accepts:
      - 'YYYY-MM'  (preferred)
      - 'YYYY'
      - 'present'  (only valid as `end`)

    Args:
        start: Start date in 'YYYY-MM' / 'YYYY' format.
        end: End date in 'YYYY-MM' / 'YYYY' format, or 'present'.

    Returns:
        Years as a float, rounded to 2 decimals (e.g. 1.5 for 18 months).
        Returns -1.0 if either input is unparseable.
    """

    def _parse(value: str) -> date | None:
        s = (value or "").strip().lower()
        if not s:
            return None
        if s == "present":
            return date.today()
        parts = s.replace("/", "-").split("-")
        try:
            year = int(parts[0])
            month = int(parts[1]) if len(parts) > 1 else 1
            month = max(1, min(12, month))
            return date(year, month, 1)
        except (ValueError, IndexError):
            return None

    s = _parse(start)
    e = _parse(end)
    if s is None or e is None:
        return -1.0
    return round((e - s).days / 365.25, 2)
