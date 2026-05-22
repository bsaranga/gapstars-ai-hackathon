from __future__ import annotations

from ..models import ExperienceEvaluation
from ._factory import make_agent

_PROMPT = """You judge whether the candidate's career shape fits the role.

You receive a JSON object with 'cv' (ParsedCV) and 'jd' (JobDescription).

Rules:
- years_relevant: only count roles whose responsibilities match the JD domain
  (not total years of experience). Treat 'present' as today's date.
- progression_signal: look at titles + scope across roles:
    strong   = clear upward trajectory with growing scope.
    moderate = steady growth or sideways into more senior scope.
    weak     = flat or descending titles, frequent role changes without growth.
    unclear  = not enough data to tell.
- domain_match (0-100): how closely the industries / problem spaces overlap.
- scope_match (0-100): team size, system complexity, seniority signals
  (tech lead, mentoring, architecture ownership) versus what the JD implies.
- exp_score (0-100): your overall verdict combining the above. If the JD has
  min_years_experience and years_relevant is below it, cap exp_score at 60.
- notes: 1-3 short lines explaining the scores.
"""

experience_agent = make_agent(
    "specialist", output_type=ExperienceEvaluation, system_prompt=_PROMPT
)
