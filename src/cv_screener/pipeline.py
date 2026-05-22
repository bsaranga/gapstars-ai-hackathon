from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from pydantic import BaseModel

from .agents import (
    aggregator_agent,
    communication_agent,
    education_agent,
    experience_agent,
    parse_cv,
    parse_jd,
    red_flags_agent,
    skills_agent,
)
from .models import (
    CommunicationEvaluation,
    EducationEvaluation,
    ExperienceEvaluation,
    JobDescription,
    ParsedCV,
    Recommendation,
    RedFlagReport,
    SkillsMatch,
)


@dataclass
class ScreeningResult:
    parsed_cv: ParsedCV
    jd: JobDescription
    skills: SkillsMatch
    experience: ExperienceEvaluation
    education: EducationEvaluation
    red_flags: RedFlagReport
    communication: CommunicationEvaluation
    recommendation: Recommendation

    def to_dict(self) -> dict:
        return {
            "parsed_cv": self.parsed_cv.model_dump(),
            "jd": self.jd.model_dump(),
            "skills": self.skills.model_dump(),
            "experience": self.experience.model_dump(),
            "education": self.education.model_dump(),
            "red_flags": self.red_flags.model_dump(),
            "communication": self.communication.model_dump(),
            "recommendation": self.recommendation.model_dump(),
        }


def _payload(*, cv: ParsedCV, jd: JobDescription) -> str:
    return json.dumps({"cv": cv.model_dump(), "jd": jd.model_dump()})


async def _run_specialist(agent, prompt: str) -> BaseModel:
    result = await agent.run(prompt)
    return result.output


async def screen(raw_cv: str, raw_jd: str) -> ScreeningResult:
    parsed_cv, jd = await asyncio.gather(parse_cv(raw_cv), parse_jd(raw_jd))

    pair_payload = _payload(cv=parsed_cv, jd=jd)
    cv_only_payload = json.dumps({"cv": parsed_cv.model_dump()})
    comm_payload = json.dumps(
        {"raw_cv": raw_cv, "summary": parsed_cv.summary}
    )

    skills, experience, education, red_flags, communication = await asyncio.gather(
        _run_specialist(skills_agent, pair_payload),
        _run_specialist(experience_agent, pair_payload),
        _run_specialist(education_agent, pair_payload),
        _run_specialist(red_flags_agent, cv_only_payload),
        _run_specialist(communication_agent, comm_payload),
    )

    agg_payload = json.dumps(
        {
            "jd": jd.model_dump(),
            "skills": skills.model_dump(),
            "experience": experience.model_dump(),
            "education": education.model_dump(),
            "red_flags": red_flags.model_dump(),
            "communication": communication.model_dump(),
        }
    )
    rec_result = await aggregator_agent.run(agg_payload)
    recommendation = rec_result.output

    return ScreeningResult(
        parsed_cv=parsed_cv,
        jd=jd,
        skills=skills,
        experience=experience,
        education=education,
        red_flags=red_flags,
        communication=communication,
        recommendation=recommendation,
    )
