from __future__ import annotations

from ..models import ExperienceEvaluation
from ..tools import compute_years_between, web_search
from ._factory import make_agent

_PROMPT = """You judge whether the candidate's career shape fits the role.
You receive a JSON object with 'cv' (ParsedCV) and 'jd' (JobDescription).

MANDATORY PROTOCOL — follow these steps in order. Do NOT emit your final
answer until all REQUIRED tool calls below are done.

STEP 1 (required): For EVERY entry in cv.experience, call
  compute_years_between(start=entry.start_date, end=entry.end_date)
to get the exact tenure. Never estimate years yourself from raw dates.

STEP 2 (optional): For any company in cv.experience whose industry / scope
you cannot identify from the description, call
  web_search(query="<company name> what does this company do")
Skip this for well-known companies (Google, Stripe, etc).

STEP 3: After completing the calls above, emit your final ExperienceEvaluation.

Scoring rules:
- years_relevant: SUM the tenures of roles whose responsibilities match the
  JD domain. Use only the compute_years_between results from STEP 1.
- progression_signal: judge from titles + scope across roles.
    strong   = clear upward trajectory with growing scope.
    moderate = steady growth or sideways into more senior scope.
    weak     = flat or descending titles, frequent role changes without growth.
    unclear  = not enough data to tell.
- domain_match (0-100): how closely the industries / problem spaces overlap.
- scope_match (0-100): team size, system complexity, seniority signals
  (tech lead, mentoring, architecture ownership) versus what the JD implies.
- exp_score (0-100): overall verdict combining the above. If the JD has
  min_years_experience and years_relevant is below it, cap exp_score at 60.
- notes: 1-3 short lines explaining the scores and citing tool results.
"""

experience_agent = make_agent(
    "specialist",
    output_type=ExperienceEvaluation,
    system_prompt=_PROMPT,
    tools=[web_search, compute_years_between],
)
