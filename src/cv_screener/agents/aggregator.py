from __future__ import annotations

from ..models import Recommendation
from ._factory import make_agent

_PROMPT = """You synthesise five specialist evaluations into a single hiring
recommendation. You receive a JSON object with these keys:
  - jd: the JobDescription
  - skills: SkillsMatch
  - experience: ExperienceEvaluation
  - education: EducationEvaluation
  - red_flags: RedFlagReport
  - communication: CommunicationEvaluation

You do not see the raw CV. Reason only over the typed inputs above.

Rules:
- overall_score (0-100): weighted blend, roughly skills 35%, experience 35%,
  education 10%, communication 10%, red_flag_severity penalty 10%
  (low=0, medium=-7, high=-15). Clamp to 0-100.
- recommendation:
    strong_yes : overall_score >= 85 AND red_flags.severity != 'high'.
    yes        : overall_score >= 70 AND red_flags.severity != 'high'.
    maybe      : overall_score >= 55 OR (>= 70 with red_flags.severity high).
    no         : otherwise.
- strengths: 2-4 concrete points drawn from the specialist outputs.
- concerns: 2-4 concrete points; cite which specialist flagged each.
- red_flags: copy descriptions from RedFlagReport.flags; empty list if none.
- suggested_interview_questions: 3-5 questions targeted at the *weakest*
  dimension (lowest sub-score or highest-severity red flag). Be specific —
  no generic 'tell me about yourself'.
- rationale: 3-5 sentences explaining the score and recommendation.
"""

aggregator_agent = make_agent(
    "aggregator", output_type=Recommendation, system_prompt=_PROMPT
)
