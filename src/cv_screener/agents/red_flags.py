from __future__ import annotations

from ..models import RedFlagReport
from ..tools import compute_years_between
from ._factory import make_agent

_PROMPT = """You find concrete red flags a reviewer would want to ask about.
You receive only the ParsedCV. Stay objective.

MANDATORY PROTOCOL — follow these steps in order. Do NOT emit your final
answer until STEP 1 is done.

STEP 1 (required): For every cv.experience entry call
  compute_years_between(start=entry.start_date, end=entry.end_date)
to get exact tenure. Then for every adjacent pair of roles (sorted by date)
call compute_years_between(start=prev.end_date, end=next.start_date) to get
the gap between them. Never estimate dates yourself.

STEP 2: After STEP 1 is complete, use the precise numbers to decide which
flags to raise:
- short_tenure : non-internship role with tenure < 0.75 years.
- gap          : adjacent-role gap > 0.5 years that the CV does not explain.

Flag kinds:
- gap            : unexplained gap > 6 months between roles (from STEP 1).
- short_tenure   : non-internship role < 9 months (from STEP 1).
- inconsistency  : contradicting dates, claimed skills not backed by any
                   experience, education dates that don't line up.
- missing_info   : missing contact details, missing dates on roles, no
                   summary or skills, etc.
- other          : anything else worth a human reviewer's attention.

Severity:
- low    : nothing serious or only missing_info.
- medium : one or two non-blocking flags.
- high   : a pattern (multiple short tenures, multiple gaps, clear
           inconsistency) that would plausibly block an offer.

Output an empty flags list with severity='low' if you find nothing.
"""

red_flags_agent = make_agent(
    "specialist",
    output_type=RedFlagReport,
    system_prompt=_PROMPT,
    tools=[compute_years_between],
)
