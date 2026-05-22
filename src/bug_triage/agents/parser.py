from __future__ import annotations

from ..models import BugReport
from ._factory import make_agent

_PROMPT = """You convert a raw bug report (markdown or free text) into the
BugReport JSON schema.

Rules:
- Only use information actually present in the text. Never invent.
- Leave a field as null / empty list if the report does not contain it.
- `steps_to_reproduce` is a list of short numbered/bulleted steps. Split a
  single multi-line paragraph into discrete steps when clearly separable.
- `environment` is a structured object with optional os, browser,
  app_version, device, user_role. Pull whatever the reporter mentioned.
- `attachments` is a list of URLs or file paths if the report links any.
- `bug_id` only if the source text contains an explicit id (e.g.
  "BUG-2026-0142").
- Do not summarise — the Analyzer agent does that. Just extract.
"""

bug_parser_agent = make_agent("parser", output_type=BugReport, system_prompt=_PROMPT)


async def parse_bug(raw_markdown: str) -> BugReport:
    result = await bug_parser_agent.run(raw_markdown)
    return result.output
