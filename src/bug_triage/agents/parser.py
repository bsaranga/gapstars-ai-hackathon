from __future__ import annotations

from ..models import BugReport
from ..prompts import load_prompt
from ._factory import make_agent

_PROMPT, PROMPT_VERSION = load_prompt("parser")

bug_parser_agent = make_agent("parser", output_type=BugReport, system_prompt=_PROMPT)


async def parse_bug(raw_markdown: str) -> BugReport:
    result = await bug_parser_agent.run(raw_markdown)
    return result.output
