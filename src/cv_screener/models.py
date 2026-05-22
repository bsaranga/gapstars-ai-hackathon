from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------- Parsed CV ----------

class EducationItem(BaseModel):
    degree: str
    field: str | None = None
    institution: str | None = None
    start_year: int | None = None
    end_year: int | None = None


class ExperienceItem(BaseModel):
    title: str
    company: str | None = None
    start_date: str | None = Field(None, description="YYYY-MM if known")
    end_date: str | None = Field(None, description="YYYY-MM or 'present'")
    description: str | None = None
    technologies: list[str] = []


class ParsedCV(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    summary: str | None = None
    education: list[EducationItem] = []
    experience: list[ExperienceItem] = []
    skills: list[str] = []
    certifications: list[str] = []
    languages: list[str] = []
    projects: list[str] = []


# ---------- Job description ----------

class JobDescription(BaseModel):
    title: str
    seniority: Literal["intern", "junior", "mid", "senior", "staff", "principal"] | None = None
    required_skills: list[str] = []
    nice_to_have_skills: list[str] = []
    min_years_experience: int | None = None
    domain: str | None = None
    description: str = ""


# ---------- Specialist outputs ----------

class SkillsMatch(BaseModel):
    matched: list[str]
    missing_required: list[str]
    missing_nice_to_have: list[str]
    skill_score: int = Field(ge=0, le=100)
    notes: str = ""


class ExperienceEvaluation(BaseModel):
    years_relevant: float
    progression_signal: Literal["strong", "moderate", "weak", "unclear"]
    domain_match: int = Field(ge=0, le=100)
    scope_match: int = Field(ge=0, le=100)
    exp_score: int = Field(ge=0, le=100)
    notes: str = ""


class EducationEvaluation(BaseModel):
    degree_match: bool
    institution_tier: Literal["top", "strong", "standard", "unknown"]
    relevant_certifications: list[str] = []
    edu_score: int = Field(ge=0, le=100)
    notes: str = ""


class RedFlag(BaseModel):
    kind: Literal["gap", "short_tenure", "inconsistency", "missing_info", "other"]
    description: str


class RedFlagReport(BaseModel):
    flags: list[RedFlag] = []
    severity: Literal["low", "medium", "high"] = "low"


class CommunicationEvaluation(BaseModel):
    clarity_score: int = Field(ge=0, le=100)
    structure_score: int = Field(ge=0, le=100)
    language_proficiency: Literal["basic", "professional", "fluent", "native"] | None = None
    notable_issues: list[str] = []


# ---------- Final aggregator output ----------

class Recommendation(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    recommendation: Literal["strong_yes", "yes", "maybe", "no"]
    strengths: list[str]
    concerns: list[str]
    red_flags: list[str]
    suggested_interview_questions: list[str]
    rationale: str
