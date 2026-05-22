from __future__ import annotations

from ..models import CommunicationEvaluation
from ._factory import make_agent

_PROMPT = """You judge how the candidate *writes*, not what they wrote about.

You receive a JSON object with 'raw_cv' (the original text) and 'summary'
(the candidate's own summary from ParsedCV, possibly null).

Rules:
- clarity_score (0-100): sentence-level clarity, active voice, concrete
  language, presence of measurable outcomes ('reduced latency by 30%').
- structure_score (0-100): document organisation — sections, bullets vs
  walls of text, consistent tense, scannability.
- language_proficiency: estimate from prose alone (basic / professional /
  fluent / native). Leave null if the CV is too short to judge.
- notable_issues: short list — typos, run-on bullets, jargon overload,
  missing impact metrics. Keep to at most 5 items.

Do not penalise content (lack of experience, missing skills). That belongs
to other agents.
"""

communication_agent = make_agent(
    "specialist", output_type=CommunicationEvaluation, system_prompt=_PROMPT
)
