from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

Severity = Literal["Critical", "High", "Medium", "Low"]
Priority = Literal["P0", "P1", "P2", "P3"]
AffectedArea = Literal[
    "auth", "payments", "ui", "api", "data", "infra", "performance", "other"
]
Seniority = Literal["junior", "mid", "senior", "staff", "principal"]
Availability = Literal["available", "limited", "out"]
StakeholderRole = Literal[
    "product_manager", "tech_lead", "engineering_manager", "qa_lead", "oncall", "other"
]
TaskType = Literal["bug", "feature", "incident", "tech_debt"]
TaskStatus = Literal["resolved", "closed", "in_progress", "wontfix"]


# ---------- Input: parsed bug report ----------


class BugEnvironment(BaseModel):
    os: str | None = None
    browser: str | None = None
    app_version: str | None = None
    device: str | None = None
    user_role: str | None = None


class BugReport(BaseModel):
    """Structured bug report extracted from the raw markdown input."""

    bug_id: str | None = None
    title: str
    description: str
    steps_to_reproduce: list[str] = []
    expected_result: str | None = None
    actual_result: str | None = None
    environment: BugEnvironment = Field(default_factory=BugEnvironment)
    reporter: str | None = None
    attachments: list[str] = []


# ---------- Agent 1 output: analysis + completeness ----------


class CompletenessVerdict(BaseModel):
    verdict: Literal["complete", "needs_more_info"]
    blocking_fields: list[str] = []
    rationale: str


class AnalysisOutput(BaseModel):
    summary: str
    affected_area: AffectedArea
    missing_information: list[str] = []
    inferred_repro_steps: list[str] | None = None
    extracted_errors: list[str] = []
    completeness: CompletenessVerdict


# ---------- Agent 2 (triage) ----------


class SuggestedAssignee(BaseModel):
    id: str
    name: str
    reason: str = Field(
        description=(
            "Must cite specific signals — matched skills and task ids returned "
            "by get_developer_history."
        )
    )


class TriageDecision(BaseModel):
    """The Triage Agent's structured output.

    Severity/priority/team are decided deterministically by the orchestrator
    before the agent runs; the agent only owns the assignee selection and the
    triage_recommendation sentence.
    """

    suggested_assignee: SuggestedAssignee
    triage_recommendation: str


# ---------- Agent 3 (artifacts) ----------


class ArtifactBundle(BaseModel):
    jira_ticket: str
    test_cases: list[str]
    duplicate_check_query: str
    handoff_note: str


# ---------- Final orchestrator output ----------


class NotifyContact(BaseModel):
    id: str
    name: str
    role: StakeholderRole


class FinalReport(BaseModel):
    bug_id: str
    summary: str
    status: Literal["Triaged", "Needs More Information"]
    severity: Severity | None = None
    priority: Priority | None = None
    missing_information: list[str] = []
    blocking_fields: list[str] = []
    suggested_repro_steps: list[str] | None = None
    suggested_owner_team: str | None = None
    suggested_assignee: SuggestedAssignee | None = None
    notify: list[NotifyContact] = []
    triage_recommendation: str | None = None
    rule_applied: str | None = None
    rationale: str | None = None
    artifacts: ArtifactBundle | None = None


# ---------- Tool I/O (slim views returned to the Triage Agent) ----------


class DeveloperSummary(BaseModel):
    """Returned by `get_team_members`. PII (email, tz) deliberately withheld."""

    id: str
    name: str
    role: str | None = None
    skills: list[str]
    seniority: Seniority | None = None
    on_call: bool = False
    availability: Availability = "available"
    open_load: int | None = Field(
        default=None,
        description="Count of in_progress tasks for this developer (derived).",
    )


class TaskSummary(BaseModel):
    """Returned by `get_developer_history`. Withholds summary/commits/reporter."""

    id: str
    type: TaskType
    title: str
    area: AffectedArea
    severity: Severity
    priority: Priority
    status: TaskStatus
    tags: list[str] = []
    resolved_at: str | None = None
    resolution_time_hours: float | None = None
    outcome_rating: int | None = None


# ---------- Config: teams.json ----------


class Developer(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str | None = None
    skills: list[str] = []
    seniority: Seniority | None = None
    on_call: bool = False
    availability: Availability = "available"
    timezone: str | None = None


class Stakeholder(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: StakeholderRole
    notify_on: list[Priority] = []


class Team(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    areas: list[AffectedArea] = Field(min_length=1)
    slack_channel: str | None = None
    jira_project: str | None = None
    escalation_contact_id: str | None = None
    developers: list[Developer] = Field(min_length=1)
    stakeholders: list[Stakeholder] = []

    @model_validator(mode="after")
    def _escalation_resolves(self) -> Team:
        if self.escalation_contact_id is None:
            return self
        ids = {s.id for s in self.stakeholders}
        if self.escalation_contact_id not in ids:
            raise ValueError(
                f"team {self.id}: escalation_contact_id "
                f"{self.escalation_contact_id!r} not in stakeholders"
            )
        return self


class TeamsConfig(BaseModel):
    version: Literal[1] = 1
    teams: list[Team] = Field(min_length=1)
    triage_lead_team_id: str | None = Field(
        default=None,
        description="Team id used as fallback when no team owns the affected_area.",
    )

    @model_validator(mode="after")
    def _unique_ids(self) -> TeamsConfig:
        team_ids: set[str] = set()
        dev_ids: set[str] = set()
        stake_ids: set[str] = set()
        for t in self.teams:
            if t.id in team_ids:
                raise ValueError(f"duplicate team id: {t.id}")
            team_ids.add(t.id)
            for d in t.developers:
                if d.id in dev_ids:
                    raise ValueError(f"duplicate developer id: {d.id}")
                dev_ids.add(d.id)
            for s in t.stakeholders:
                if s.id in stake_ids:
                    raise ValueError(f"duplicate stakeholder id: {s.id}")
                stake_ids.add(s.id)
        if (
            self.triage_lead_team_id is not None
            and self.triage_lead_team_id not in team_ids
        ):
            raise ValueError(
                f"triage_lead_team_id {self.triage_lead_team_id!r} not in teams"
            )
        return self

    def find_team_for_area(self, area: AffectedArea) -> Team | None:
        for t in self.teams:
            if area in t.areas:
                return t
        if self.triage_lead_team_id:
            for t in self.teams:
                if t.id == self.triage_lead_team_id:
                    return t
        return None

    def get_team(self, team_id: str) -> Team | None:
        for t in self.teams:
            if t.id == team_id:
                return t
        return None


# ---------- Config: tasks.json ----------


class TaskRecord(BaseModel):
    id: str
    type: TaskType
    title: str
    summary: str | None = None
    assignee_id: str
    reporter: str | None = None
    area: AffectedArea
    severity: Severity
    priority: Priority
    status: TaskStatus
    tags: list[str] = []
    opened_at: str
    resolved_at: str | None = None
    resolution_time_hours: float | None = None
    related_commits: list[str] = []
    outcome_rating: int | None = Field(default=None, ge=1, le=5)

    @model_validator(mode="after")
    def _resolved_requires_date(self) -> TaskRecord:
        if self.status in ("resolved", "closed") and not self.resolved_at:
            raise ValueError(
                f"task {self.id}: resolved_at required when status={self.status}"
            )
        return self


class TasksConfig(BaseModel):
    version: Literal[1] = 1
    tasks: list[TaskRecord] = []

    @model_validator(mode="after")
    def _unique_ids(self) -> TasksConfig:
        seen: set[str] = set()
        for t in self.tasks:
            if t.id in seen:
                raise ValueError(f"duplicate task id: {t.id}")
            seen.add(t.id)
        return self

    def cross_validate(self, teams: TeamsConfig) -> None:
        """Ensure every assignee_id resolves to a known developer."""
        dev_ids = {d.id for t in teams.teams for d in t.developers}
        for task in self.tasks:
            if task.assignee_id not in dev_ids:
                raise ValueError(
                    f"task {task.id}: assignee_id {task.assignee_id!r} "
                    "not found in any team's developers"
                )


# ---------- Config: rules.json (severity / priority rule table) ----------


class RuleMatcher(BaseModel):
    """Conditions a bug must satisfy for a rule to fire.

    All listed conditions are ANDed; conditions whose list is empty are
    skipped. Keyword checks are substring matches against a normalised
    lowercase haystack built from the bug title, description,
    actual_result, the analyzer's summary, and extracted_errors.
    """

    any_keywords: list[str] = Field(
        default_factory=list,
        description="Match if ANY of these substrings appear in the bug text.",
    )
    all_keywords: list[str] = Field(
        default_factory=list,
        description="Match only if ALL of these substrings appear.",
    )
    exclude_keywords: list[str] = Field(
        default_factory=list,
        description="Match only if NONE of these substrings appear.",
    )
    affected_areas: list[AffectedArea] = Field(
        default_factory=list,
        description="Match if the analyzer's affected_area is in this list.",
    )
    environment_substrings: list[str] = Field(
        default_factory=list,
        description=(
            "Match only if at least one of these substrings appears in the "
            "bug's environment.app_version (or anywhere in the haystack). "
            "Typical use: gate a rule to production-only reports."
        ),
    )

    def is_empty(self) -> bool:
        """A rule with no conditions matches everything (the catch-all default)."""
        return not (
            self.any_keywords
            or self.all_keywords
            or self.exclude_keywords
            or self.affected_areas
            or self.environment_substrings
        )


class TriageRule(BaseModel):
    """A single severity/priority rule. Evaluated in order; first match wins."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str
    severity: Severity
    priority: Priority
    match: RuleMatcher = Field(default_factory=RuleMatcher)
    notes: str | None = None


class TriageRuleSummary(BaseModel):
    """Returned by the `get_triage_rules` tool — same shape as TriageRule.

    Withholding nothing: the agent benefits from seeing the matchers so it
    can explain *why* the orchestrator picked the rule that fired.
    """

    id: str
    description: str
    severity: Severity
    priority: Priority
    match: RuleMatcher
    notes: str | None = None


class TriageRulesConfig(BaseModel):
    """Severity / priority rule table loaded from `config/rules.json`."""

    version: Literal[1] = 1
    rules: list[TriageRule] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> TriageRulesConfig:
        seen: set[str] = set()
        for r in self.rules:
            if r.id in seen:
                raise ValueError(f"duplicate rule id: {r.id}")
            seen.add(r.id)
        return self

    @model_validator(mode="after")
    def _ends_with_default(self) -> TriageRulesConfig:
        """The last rule must be a catch-all (empty match) so every bug
        gets a verdict. This is enforced at load time so config edits
        can't silently leave a hole.
        """
        last = self.rules[-1]
        if not last.match.is_empty():
            raise ValueError(
                f"the last rule (id={last.id!r}) must have an empty `match` "
                "block so it acts as the default catch-all. Move it to the "
                "end of the list, or add a default-* rule after it."
            )
        # And no other rule may be a catch-all (would shadow later rules).
        for r in self.rules[:-1]:
            if r.match.is_empty():
                raise ValueError(
                    f"rule {r.id!r} has an empty `match` block but is not "
                    "the last rule — it would shadow every rule after it."
                )
        return self

    def get_rule(self, rule_id: str) -> TriageRule | None:
        for r in self.rules:
            if r.id == rule_id:
                return r
        return None
