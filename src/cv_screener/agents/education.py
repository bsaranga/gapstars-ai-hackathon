from __future__ import annotations

from ..models import EducationEvaluation
from ._factory import make_agent

_PROMPT = """You judge formal education + certifications against the JD.

You receive a JSON object with 'cv' (ParsedCV) and 'jd' (JobDescription).

Rules:
- degree_match: True if the candidate's highest relevant degree satisfies what
  the JD requires. If the JD does not state a degree requirement, treat that
  as satisfied (degree_match=True). Never invent a requirement.
- institution_tier: be conservative.
    top      = globally well-known top-tier (MIT, Stanford, Cambridge, etc).
    strong   = nationally recognised strong program.
    standard = ordinary accredited institution.
    unknown  = you cannot tell; prefer this over guessing.
- relevant_certifications: only certifications relevant to this JD (e.g. AWS
  for cloud roles, CFA for finance). Ignore generic productivity certs.
- edu_score (0-100): if degree_match is False and JD requires one, max 50.
  Otherwise score based on tier and relevance of certs.
- notes: 1-3 short lines.
"""

education_agent = make_agent(
    "specialist", output_type=EducationEvaluation, system_prompt=_PROMPT
)
