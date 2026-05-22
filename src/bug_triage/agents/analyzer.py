from __future__ import annotations

from ..models import AnalysisOutput
from ..prompts import load_prompt
from ._factory import make_agent

_PROMPT, PROMPT_VERSION = load_prompt("analyzer")

analyzer_agent = make_agent(
    "analyzer", output_type=AnalysisOutput, system_prompt=_PROMPT
)
