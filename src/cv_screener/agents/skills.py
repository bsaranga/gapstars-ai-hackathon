from __future__ import annotations

from ..models import SkillsMatch
from ._factory import make_agent

_PROMPT = """You judge how well a candidate's skills cover a job's requirements.

You receive a JSON object with two keys: 'cv' (ParsedCV) and 'jd' (JobDescription).

Rules:
- For every JD required_skill and nice_to_have_skill, decide if the candidate
  has it. Allow obvious synonyms (PG = Postgres, JS = JavaScript, k8s =
  Kubernetes). Skills can be inferred from project / experience descriptions,
  not only the explicit skills list.
- matched: skills the candidate clearly has that are listed in the JD.
- missing_required: JD required_skills with no evidence in the CV.
- missing_nice_to_have: JD nice_to_have_skills with no evidence in the CV.
- skill_score (0-100): weight required heavily. Missing one required skill
  should drop the score meaningfully (~15-25). Missing nice-to-haves are
  small deductions (~2-5 each). Full required coverage with all nice-to-haves
  is 95+.
- notes: 1-3 short lines on close-but-not-exact matches or inferred skills.
"""

skills_agent = make_agent("specialist", output_type=SkillsMatch, system_prompt=_PROMPT)
