from __future__ import annotations

from ..models import JobDescription, ParsedCV
from ._factory import make_agent

_CV_PROMPT = """You extract structured information from a raw CV / resume.

Rules:
- Only use information actually present in the text. Never invent.
- Leave a field as null / empty list if the CV does not contain it.
- Dates: prefer YYYY-MM; use 'present' for current roles.
- Skills must be the candidate's tools/technologies, not soft skills.
- Do not summarise. Be faithful to what the candidate wrote.
"""

_JD_PROMPT = """You extract a structured Job Description from a job posting.

Rules:
- required_skills: hard requirements the posting calls out as required.
- nice_to_have_skills: anything described as 'plus', 'bonus', 'nice to have'.
- min_years_experience: integer; only set if the posting states a number.
- seniority: pick the closest of intern/junior/mid/senior/staff/principal,
  else leave null.
- description: a short (1-3 sentence) summary of the role.
- Do not invent requirements not in the text.
"""

cv_parser_agent = make_agent("parser", output_type=ParsedCV, system_prompt=_CV_PROMPT)
jd_parser_agent = make_agent("parser", output_type=JobDescription, system_prompt=_JD_PROMPT)


async def parse_cv(raw_text: str) -> ParsedCV:
    result = await cv_parser_agent.run(raw_text)
    return result.output


async def parse_jd(raw_text: str) -> JobDescription:
    result = await jd_parser_agent.run(raw_text)
    return result.output
