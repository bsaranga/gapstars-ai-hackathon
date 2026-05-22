# Bug Triage AI Workflow — Design Document

## 1. Overview

A multi-agent AI workflow that ingests raw bug reports and produces structured triage decisions. The system reduces manual triage time, enforces consistent severity/priority rules, and flags incomplete reports before they reach engineers.

**Core principle:** Separation of concerns between *understanding the bug* (Analyzer) and *deciding what to do with it* (Triage). A third optional agent generates downstream artifacts (Jira ticket, test cases, handoff notes).

---

## 2. Architecture

### 2.1 High-Level Flow

```
┌──────────────┐
│ Bug Report   │  (user submission via form/API)
│ Input Form   │
└──────┬───────┘
       │
       ▼
┌─────────────────────┐
│ Orchestrator        │  (validates input, loads teams.json
│ (Workflow Engine)   │   + tasks.json, picks team, routes to
│                     │   agents, aggregates results)
└──────┬──────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│ Agent 1: Bug Analyzer                   │
│  • Parse + summarize                    │
│  • Detect missing fields                │
│  • Suggest clearer repro steps          │
│  • Emit completeness verdict            │
│  • Output: structured analysis JSON     │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│ Completeness Gate (orchestrator)        │
│  • If incomplete → short-circuit:       │
│      status = "Needs More Information"  │
│      Triage agent is NOT invoked        │
│  • If complete → continue to Agent 2    │
└──────┬──────────────────────────────────┘
       │ (only if complete)
       ▼
┌─────────────────────────────────────────┐
│ Agent 2: Triage Agent                   │
│  • Classify severity (rule + LLM)       │
│  • Assign priority                      │
│  • Pick assignee via tools:             │
│      ─ get_team_members (teams.json)    │
│      ─ get_developer_history (tasks.json)│
│  • Output: triage decision JSON         │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│ Agent 3 (Stretch): Artifact Generator   │
│  • Jira ticket format                   │
│  • Test case suggestions                │
│  • Duplicate check query                │
│  • Developer handoff note               │
└──────┬──────────────────────────────────┘
       │
       ▼
┌──────────────┐
│ Final Report │  (rendered for user / posted to Jira)
└──────────────┘
```

### 2.2 Why Two Agents (Not One)

| Concern | Reason |
|---|---|
| Single-responsibility | Analyzer focuses on comprehension; Triage focuses on decisions. Easier to evaluate and tune independently. |
| Prompt size | Smaller, focused prompts produce more reliable JSON output. |
| Testability | Each agent can be unit-tested with fixture bug reports. |
| Cost control | Triage agent can be a cheaper/faster model since it operates on already-structured input. |
| Auditability | Each step produces a traceable artifact — useful for explaining "why was this marked Critical?" |

---

## 3. Input Schema

```json
{
  "bug_id": "string (optional, auto-generated if absent)",
  "title": "string (required)",
  "description": "string (required)",
  "steps_to_reproduce": "string | string[] (optional)",
  "expected_result": "string (optional)",
  "actual_result": "string (optional)",
  "environment": {
    "os": "string",
    "browser": "string",
    "app_version": "string",
    "device": "string",
    "user_role": "string"
  },
  "reporter": "string (optional)",
  "attachments": "string[] (optional — URLs or paths)"
}
```

**Validation rules at the orchestrator level (before any LLM call):**
- `title` and `description` must be non-empty.
- If both are missing, reject with `400 — insufficient input` (don't waste a model call).
- Trim, normalize whitespace, strip HTML.

---

## 4. Agent 1 — Bug Analyzer

### 4.1 Responsibilities
1. Produce a concise one- or two-sentence **summary** of the bug.
2. Identify the **affected feature area** (auth, payments, UI, API, infra, etc.).
3. List **missing information** the engineer would need.
4. If repro steps are vague or absent, **suggest clearer steps** inferred from the description.
5. Extract any **error messages, codes, or stack-trace fragments** mentioned.
6. Emit an explicit **completeness verdict** (`completeness`) so the orchestrator can decide whether to invoke the Triage Agent or short-circuit the run with a `Needs More Information` response. The Analyzer does not invoke triage itself.

### 4.2 Prompt Skeleton

```
You are a senior QA engineer analyzing a bug report.

INPUT:
<bug_report_json>

TASKS:
1. Write a 1–2 sentence summary.
2. Classify the affected area: [auth, payments, ui, api, data, infra, performance, other].
3. List missing information (any of: repro steps, expected result, actual result,
   environment, user role, timestamp, frequency, error code, screenshots).
4. If repro steps are unclear or absent, propose 3–6 numbered steps inferred from
   the description. Mark them clearly as INFERRED.
5. Extract any error messages, codes, or stack traces verbatim.

OUTPUT: valid JSON only, matching this schema:
{
  "summary": string,
  "affected_area": string,
  "missing_information": string[],
  "inferred_repro_steps": string[] | null,
  "extracted_errors": string[],
  "completeness": {
    "verdict": "complete" | "needs_more_info",
    "blocking_fields": string[],   // subset of missing_information that BLOCK triage
    "rationale": string             // 1 sentence
  }
}

Completeness rules the Analyzer must apply (deterministic — phrased as
prompt rules so the LLM is consistent):
- verdict = "needs_more_info" if any of:
    • actual_result is empty AND no inferred_repro_steps could be produced
    • title or description is too vague to identify affected_area
      (you would have to guess the area)
    • a production-severity claim is made but environment is absent
- Otherwise verdict = "complete".
- blocking_fields lists ONLY the missing items that drove a
  needs_more_info verdict; informational gaps go in missing_information
  but NOT in blocking_fields.
```

### 4.3 Output Schema

```json
{
  "summary": "Checkout fails with HTTP 500 when applying a discount code on Safari.",
  "affected_area": "payments",
  "missing_information": [
    "Exact discount code that triggers the failure",
    "Whether the issue reproduces on other browsers",
    "User account type (guest vs logged-in)"
  ],
  "inferred_repro_steps": [
    "Add any item to the cart",
    "Proceed to checkout",
    "Enter a discount code in the promo field",
    "Click 'Apply'"
  ],
  "extracted_errors": ["HTTP 500", "PromoService.applyDiscount NullReferenceException"],
  "completeness": {
    "verdict": "complete",
    "blocking_fields": [],
    "rationale": "Affected area is clear (payments) and a repro path could be inferred from the description."
  }
}
```

### 4.4 Completeness Gate (orchestrator, between Agent 1 and Agent 2)

Before invoking the Triage Agent, the orchestrator inspects
`analysis.completeness`:

```python
# pseudocode
analysis = analyzer_agent.run(report)

if analysis["completeness"]["verdict"] == "needs_more_info":
    return {
        "bug_id": report.bug_id,
        "summary": analysis["summary"],
        "status": "Needs More Information",
        "missing_information": analysis["missing_information"],
        "blocking_fields": analysis["completeness"]["blocking_fields"],
        "rationale": analysis["completeness"]["rationale"],
        # NB: no severity, no priority, no team, no assignee.
        # Triage Agent was NOT invoked — no tool calls, no LLM spend.
    }

# else: proceed to Triage (Agent 2)
decision = triage(analysis, report, teams, tasks)
```

Why gate here, not inside Triage:
- **Cost.** Triage uses tool-calling and a stronger model; rejecting at
  the gate avoids those calls entirely for incomplete reports.
- **Single source of truth.** Completeness is judged once, by the agent
  that already understands the report. Triage doesn't need to re-derive
  it.
- **Clean output contract.** A `Needs More Information` response cannot
  accidentally carry a severity/priority guess — those fields simply
  don't exist on the short-circuit path.
- **Auditability.** A single boolean in `analysis.completeness.verdict`
  drives the branch; trivial to log and to write fixtures against.

The orchestrator may additionally apply a **hard pre-Analyzer gate** for
purely-syntactic failures (empty `title` AND empty `description`) —
already covered by §3's input validation — so the Analyzer is not even
invoked for empty submissions.

---

## 5. Agent 2 — Triage Agent

### 5.1 Responsibilities
1. Assign **severity** (impact on the system/users) — driven by deterministic rules (§5.3), LLM only for residual cases.
2. Assign **priority** (how urgently it should be worked on) — same rule-first approach.
3. Recommend an **owner team** — the orchestrator looks this up deterministically from `affected_area` before calling the agent.
4. Recommend a specific **assignee** by calling the two tools in §5.7: `get_team_members` to inspect the roster, then `get_developer_history` on the most plausible candidates to weigh actual track record.
5. Produce a **triage recommendation** sentence and a `reason` for the chosen assignee that cites the specific signals it used (matched skills, task ids from history).

The **notification list** is built deterministically by the orchestrator from the final priority (§5.6) — not by the agent.

### 5.2 Severity vs Priority

These are commonly conflated; the workflow treats them as distinct:

- **Severity** = *technical/user impact* (Critical, High, Medium, Low).
- **Priority** = *scheduling urgency* (P0, P1, P2, P3). Influenced by severity *plus* business context (release proximity, customer tier, etc.).

### 5.3 Decision Logic (Required Rules)

Applied **deterministically before** any LLM judgment — these are guardrails, not suggestions.

| Condition | Severity | Priority | Note |
|---|---|---|---|
| Production outage / data loss / security breach | Critical | P0 | Page on-call |
| Payment failure / authentication broken | High | P1 | |
| Core feature broken for many users | High | P1 | |
| Feature broken for some users, workaround exists | Medium | P2 | |
| UI cosmetic issue (alignment, color, typo) | Low | P3 | |

> Note: the previous "Missing reproduction steps AND missing actual result → Needs More Information" row has moved out of this table. That check now happens **before** triage runs, in the orchestrator's Completeness Gate (§4.4). By the time the Triage Agent is invoked, completeness is already guaranteed.

**Implementation note:** Express these as a rules table (JSON or YAML) the agent consults. The LLM only handles the residual cases that don't match a rule. This makes the "Critical = outage" promise auditable and testable.

### 5.4 Owner/Team Mapping

Team and developer data **is not hard-coded** — it lives in an external
`teams.json` config file (see §5.6). The orchestrator loads it at startup
and matches `analysis.affected_area` against each team's `areas` list.
A condensed example:

| Affected area | Default team (from `teams.json`) |
|---|---|
| auth | Identity Team |
| payments | Billing Team |
| ui | Frontend Team |
| api | Backend / Platform |
| data | Data Platform |
| infra | DevOps / SRE |
| performance | Performance Working Group |
| other | Triage Lead (manual review) |

Edit `config/teams.json`, not this table, to change ownership.

### 5.5 Output Schema

```json
{
  "severity": "High",
  "priority": "P1",
  "status": "Triaged | Needs More Information",
  "suggested_owner_team": "Billing Team",
  "suggested_assignee": {
    "id": "dev-alice",
    "name": "Alice Chen",
    "reason": "Matched skills: stripe, payments. On-call. Senior."
  },
  "notify": [
    {"id": "pm-dana", "name": "Dana Park", "role": "product_manager"},
    {"id": "tl-carol", "name": "Carol Lee", "role": "tech_lead"}
  ],
  "triage_recommendation": "Assign to Alice Chen (Billing). Discount-code path on Safari is failing for all users; rolling release likely affected.",
  "rule_applied": "Payment failure → High / P1"
}
```

The `rule_applied` field makes the severity/priority decision explainable
(deterministic — see §5.3). The `suggested_assignee.reason` is written by
the Triage Agent itself, after calling the tools described in §5.7, and
must cite the specific signals it used (matched skills, recent similar
task ids, on-call status, etc.).

### 5.6 Team Configuration File

#### File location

- Path: `config/teams.json` at the project root. Override with env var
  `BUG_TRIAGE_TEAMS_FILE`.
- Loaded once at orchestrator startup and cached in memory. SIGHUP (or
  filesystem watch in development) triggers a reload.
- Validated at load time using a Pydantic model (`TeamsConfig`). Boot
  fails loudly if: duplicate team ids, duplicate developer ids across
  teams, unknown `affected_area` value in any `areas` list, or any
  `escalation_contact_id` that does not resolve to a stakeholder on the
  same team.

#### Schema

```json
{
  "version": 1,
  "teams": [
    {
      "id": "billing",
      "name": "Billing Team",
      "areas": ["payments", "subscriptions", "invoicing"],
      "slack_channel": "#billing-bugs",
      "jira_project": "BILL",
      "escalation_contact_id": "tl-carol",
      "developers": [
        {
          "id": "dev-alice",
          "name": "Alice Chen",
          "email": "alice@example.com",
          "role": "Senior Engineer",
          "skills": ["stripe", "payments", "java", "kafka", "postgres"],
          "seniority": "senior",
          "on_call": true,
          "availability": "available",
          "timezone": "America/New_York"
        },
        {
          "id": "dev-ben",
          "name": "Ben Ortiz",
          "email": "ben@example.com",
          "role": "Engineer",
          "skills": ["java", "spring", "payments"],
          "seniority": "mid",
          "on_call": false,
          "availability": "out",
          "timezone": "Europe/Berlin"
        }
      ],
      "stakeholders": [
        {
          "id": "pm-dana",
          "name": "Dana Park",
          "role": "product_manager",
          "email": "dana@example.com",
          "notify_on": ["P0", "P1"]
        },
        {
          "id": "tl-carol",
          "name": "Carol Lee",
          "role": "tech_lead",
          "email": "carol@example.com",
          "notify_on": ["P0", "P1", "P2"]
        },
        {
          "id": "em-erik",
          "name": "Erik Voss",
          "role": "engineering_manager",
          "email": "erik@example.com",
          "notify_on": ["P0"]
        }
      ]
    }
  ]
}
```

#### Field semantics

**Team-level**

| Field | Type | Required | Purpose |
|---|---|---|---|
| `id` | string (kebab-case) | yes | Stable key referenced by rules and logs; never changes |
| `name` | string | yes | Display name used in Jira ticket / output |
| `areas` | string[] | yes | `affected_area` values this team owns. Triage matches `analysis.affected_area` against this list; first match wins |
| `slack_channel` | string | optional | Used by Artifact Generator for the handoff note |
| `jira_project` | string | optional | Project key prefix on generated tickets |
| `escalation_contact_id` | string | optional | Stakeholder id to cc on P0; falls back to first `tech_lead` stakeholder if absent |
| `developers` | Developer[] | yes (min 1) | Pool from which `suggested_assignee` is chosen |
| `stakeholders` | Stakeholder[] | optional | Non-developer contacts |

**Developer**

| Field | Type | Required | Purpose |
|---|---|---|---|
| `id` | string | yes | Stable, referenced in output |
| `name`, `email` | string | yes | Display + contact |
| `role` | string | optional | Free text ("Senior Engineer", "Staff", etc.) |
| `skills` | string[] | yes | Lowercase tags. Triage intersects with tokens from `extracted_errors` + `affected_area` to score candidates |
| `seniority` | enum: `junior` \| `mid` \| `senior` \| `staff` \| `principal` | optional | Tie-breaker — higher for P0/P1, lower for P3 so juniors get growth tickets |
| `on_call` | bool | optional | If true, preferred for P0 |
| `availability` | enum: `available` \| `limited` \| `out` | optional | `out` developers excluded from assignment |
| `timezone` | IANA tz string | optional | Reserved for future timezone-aware routing |

**Stakeholder**

| Field | Type | Required | Purpose |
|---|---|---|---|
| `id`, `name`, `email` | string | yes | |
| `role` | enum: `product_manager` \| `tech_lead` \| `engineering_manager` \| `qa_lead` \| `oncall` \| `other` | yes | Drives default notification behaviour and escalation lookup |
| `notify_on` | priority[] | yes | Which priorities trigger a cc — e.g. `["P0", "P1"]` |

#### Team selection (deterministic, in orchestrator)

Team selection itself stays deterministic — it's a pure lookup:

1. Find candidate team(s): `team.areas` contains `analysis.affected_area`.
   If none match, fall back to a configured `triage_lead` team.
2. The team's `id` is then passed to the Triage Agent and used as the
   parameter for the `get_team_members` tool (§5.7).

Assignee selection itself is **not** deterministic any more; the Triage
Agent decides via the tools in §5.7. The orchestrator only computes the
notification list once the agent has produced a final priority:

- every stakeholder where `stakeholder.notify_on` contains the final
  `priority`, **plus**
- the team's `escalation_contact_id` if `priority == "P0"` (deduped).

---

### 5.7 Tools available to the Triage Agent

The Triage Agent never receives `teams.json` or `tasks.json` directly in
its prompt. Instead it is given two tools that return slim, filtered
slices on demand. This keeps the prompt small, makes lookups auditable
(every tool call is logged), and lets the agent decide what context it
actually needs to make a defensible assignee call.

Both tools are implemented as Pydantic-AI `@agent.tool` functions backed
by the validated `TeamsConfig` / `TasksConfig` Pydantic models loaded at
startup. They are pure reads — no side effects, no LLM calls inside.

#### Tool 1 — `get_team_members`

**Purpose:** Return the roster of a single team for the agent to scan.

**Signature:**

```python
@triage_agent.tool
def get_team_members(
    ctx: RunContext[TriageDeps],
    team_id: str,
    include_unavailable: bool = False,
) -> list[DeveloperSummary]:
    """Return developers on `team_id`.

    By default, developers with availability == "out" are excluded.
    The agent passes the team_id resolved by the orchestrator from
    `analysis.affected_area`.
    """
```

**`DeveloperSummary` (output item):**

```json
{
  "id": "dev-alice",
  "name": "Alice Chen",
  "role": "Senior Engineer",
  "skills": ["stripe", "payments", "java", "kafka", "postgres"],
  "seniority": "senior",
  "on_call": true,
  "availability": "available"
}
```

`email` and `timezone` are intentionally **not** returned — the agent
doesn't need them, and dropping them reduces prompt tokens and PII leak
surface. The orchestrator re-hydrates contact details from the chosen
`id` when building the artifact in §6.

**Errors:** raises `TeamNotFound(team_id)` — surfaced to the agent as a
tool-error message it must recover from (re-call with the fallback
`triage_lead` team).

#### Tool 2 — `get_developer_history`

**Purpose:** Return the recent tasks a specific developer has worked on,
so the agent can weigh actual track record (not just self-reported
skills) when picking an assignee.

**Signature:**

```python
@triage_agent.tool
def get_developer_history(
    ctx: RunContext[TriageDeps],
    developer_id: str,
    area: str | None = None,
    limit: int = 10,
    since_days: int = 365,
) -> list[TaskSummary]:
    """Return up to `limit` tasks resolved by `developer_id`.

    Filters:
      - area: if set, only tasks whose `area` matches (use to narrow to
        the current bug's affected_area).
      - since_days: only tasks resolved within this window.

    Ordering: most recent first.
    """
```

**`TaskSummary` (output item):**

```json
{
  "id": "BUG-2025-0421",
  "type": "bug",
  "title": "Stripe webhook retry loop causing duplicate charges",
  "area": "payments",
  "severity": "High",
  "priority": "P1",
  "status": "resolved",
  "tags": ["stripe", "webhooks", "payments"],
  "resolved_at": "2025-11-05",
  "resolution_time_hours": 18,
  "outcome_rating": 5
}
```

The full task record (with `summary`, `related_commits`, `reporter`) is
withheld unless explicitly needed — see §5.8 for the full schema.

**Errors:** raises `DeveloperNotFound(developer_id)`.

#### How the agent is expected to use the tools

The system prompt tells the agent:

1. Call `get_team_members(team_id)` once for the team the orchestrator
   selected.
2. Identify the 2–3 most plausible candidates based on `skills` overlap
   with `analysis.affected_area` and tokens from
   `analysis.extracted_errors`.
3. For each candidate, call
   `get_developer_history(developer_id, area=analysis.affected_area)` to
   see whether they've actually shipped fixes in this area recently.
4. Pick the best candidate. Prefer: (a) on-call for P0, (b) demonstrated
   recent resolution of similar tasks, (c) shorter `resolution_time_hours`
   on comparable severity, (d) higher seniority for P0/P1 and lower for
   P2/P3 so juniors get growth tickets.
5. Populate `suggested_assignee.reason` with the **specific signals
   used** — naming the matched skills *and* citing one or two task ids
   from history when relevant. Reasons that don't cite tool output are
   rejected by the orchestrator (logged + fall back to skills-only
   match).

#### Why tools instead of injecting both files into the prompt

| | Inject everything | Tool-driven (chosen) |
|---|---|---|
| Prompt size | Grows with company size | Constant — only the chosen team's roster + history slices |
| Auditability | One opaque prompt | Every tool call logged with args + result hash |
| PII surface | Full file exposed every turn | Only fields the tool returns |
| Stale data | Cached at run start | Tool reads current config each call (with the in-memory cache) |
| Hallucinated ids | Possible | Tool errors surface as tool errors; agent must recover |

#### Caveats

- Tool calls add round-trips. Budget: at most 1 `get_team_members` call
  and 3 `get_developer_history` calls per bug. The agent's system prompt
  states this budget explicitly; the orchestrator enforces it by
  rejecting the run if exceeded.
- The Triage model must support OpenAI-style function calling. If the
  configured model doesn't, the orchestrator falls back to the
  deterministic skills-only scorer (kept around as a fallback path —
  see §11).
- Tools are pure reads. Any write (e.g. recording the new assignment
  back into `tasks.json`) happens in Agent 3 / the orchestrator, never
  inside a tool exposed to Agent 2.

---

### 5.8 Task History Configuration File

#### Purpose

`tasks.json` is the historical record of tasks each team member has
worked on. It is the data source behind `get_developer_history` (§5.7)
and is the primary way the Triage Agent moves beyond self-reported
`skills` to evidence-based assignee selection.

#### File location

- Path: `config/tasks.json` at the project root. Override with env var
  `BUG_TRIAGE_TASKS_FILE`.
- For the assessment / demo, this is a static dummy-data JSON file. In
  production it would be hydrated from Jira / GitHub / the data
  warehouse — the tool interface (§5.7) is stable across either source.
- Validated at load time using a Pydantic model (`TasksConfig`). Boot
  fails loudly if: duplicate task ids, any `assignee_id` that does not
  resolve to a known developer in `teams.json`, or an `area` value
  outside the §4.2 enum.

#### Schema

```json
{
  "version": 1,
  "tasks": [
    {
      "id": "BUG-2025-0421",
      "type": "bug",
      "title": "Stripe webhook retry loop causing duplicate charges",
      "summary": "Idempotency key was missing on the retry handler; added one and backfilled affected customers.",
      "assignee_id": "dev-alice",
      "reporter": "qa-lopez",
      "area": "payments",
      "severity": "High",
      "priority": "P1",
      "status": "resolved",
      "tags": ["stripe", "webhooks", "payments", "idempotency"],
      "opened_at": "2025-11-03",
      "resolved_at": "2025-11-05",
      "resolution_time_hours": 18,
      "related_commits": ["abc123f", "def456a"],
      "outcome_rating": 5
    },
    {
      "id": "FEAT-2025-0388",
      "type": "feature",
      "title": "Add per-merchant rate limiting to checkout API",
      "summary": "Token-bucket per merchant_id; 99p latency unchanged.",
      "assignee_id": "dev-ben",
      "reporter": "pm-dana",
      "area": "payments",
      "severity": "Medium",
      "priority": "P2",
      "status": "resolved",
      "tags": ["rate-limiting", "api", "payments"],
      "opened_at": "2025-09-12",
      "resolved_at": "2025-09-26",
      "resolution_time_hours": 64,
      "related_commits": ["1234abc"],
      "outcome_rating": 4
    }
  ]
}
```

#### Field semantics

| Field | Type | Required | Purpose |
|---|---|---|---|
| `id` | string | yes | Stable task identifier (Jira key, GitHub issue#, etc.) |
| `type` | enum: `bug` \| `feature` \| `incident` \| `tech_debt` | yes | Helps the agent weigh comparable past work |
| `title` | string | yes | Short headline |
| `summary` | string | optional | 1–3 sentences on what was done. **Withheld** from the default tool output to keep prompts small; can be opt-in via a future tool param |
| `assignee_id` | string (FK → `teams.json` developer) | yes | The developer credited with resolving the task |
| `reporter` | string | optional | Free-text id of the person who filed it |
| `area` | string (same enum as §4.2 `affected_area`) | yes | Used by `get_developer_history(area=...)` to filter |
| `severity` | enum (same as §5.5) | yes | |
| `priority` | enum (same as §5.5) | yes | |
| `status` | enum: `resolved` \| `closed` \| `in_progress` \| `wontfix` | yes | Only `resolved` / `closed` count as "track record"; `in_progress` signals current load |
| `tags` | string[] | optional | Lowercase free-form tags — extra signal beyond `area` for skill match |
| `opened_at`, `resolved_at` | ISO date | yes / optional | `resolved_at` required when status is `resolved` or `closed` |
| `resolution_time_hours` | number | optional | Used by the agent as a quality signal (faster ≠ always better, but a useful tie-breaker) |
| `related_commits` | string[] | optional | Reserved — not exposed via the default tool |
| `outcome_rating` | int 1–5 | optional | Reporter or peer rating; the agent treats this as a soft signal, not a hard rank |

#### What the LLM sees vs what it does not

`get_developer_history` returns the `TaskSummary` shape from §5.7 — i.e.
**no** `summary`, **no** `related_commits`, **no** `reporter`. These
fields exist in the file for downstream artifact generation and human
inspection but are deliberately not pushed into the agent's prompt
unless a future tool extension asks for them explicitly.

#### Current-load signal (derived, not stored)

The orchestrator computes a derived metric from `tasks.json` at run
start: `open_tasks_per_developer = count(status == "in_progress")
group by assignee_id`. This is **not** a tool — it is injected directly
into the agent's system context for the matched team's developers, so
the agent can de-prioritise people already at capacity without making
an extra tool call for it. Cap shown in the prompt: 3 open tasks =
"loaded", 5+ = "overloaded".

---

## 6. Agent 3 (Stretch) — Artifact Generator

Runs only after Agents 1 and 2 succeed and status is `Triaged`.

### 6.1 Outputs

**Jira-style ticket:**
```
Title:        [PAY] Checkout 500 on Safari when applying discount code
Type:         Bug
Severity:     High
Priority:     P1
Component:    Payments / Checkout
Assignee:     Alice Chen           ← from suggested_assignee.name
CC:           Dana Park, Carol Lee ← from notify[]
Environment:  Safari 17.x, macOS 14, Production v4.12
Description:  <summary + actual vs expected>
Steps:        <inferred or provided>
```

The project key (`PAY` / `BILL` etc.) comes from `team.jira_project`.

**Test cases:** 2–4 cases covering the failure path and adjacent regressions (e.g., "discount code on Chrome", "invalid discount code on Safari", "discount code with logged-out user").

**Duplicate check query:** A search string suitable for Jira/GitHub search (`"discount" AND "Safari" AND "500"` plus a date range).

**Developer handoff note:** 3–5 sentences for the on-call engineer — what's broken, where to look first, what to verify. Posted to the team's `slack_channel`, cc'ing the `notify` list.

---

## 7. Decision Logic Implementation

A hybrid approach beats pure-LLM for triage rules:

```python
# pseudocode — called by the orchestrator only after the
# Completeness Gate (§4.4) has confirmed analysis is complete.
def triage(analysis: dict, report: dict,
           teams: TeamsConfig, tasks: TasksConfig) -> dict:
    assert analysis["completeness"]["verdict"] == "complete", \
        "Gate violation: triage() invoked on an incomplete analysis"

    # 1. Deterministic severity/priority rules
    if is_production_outage(report, analysis):
        decision = rule("Critical", "P0", "Production outage")
    elif analysis["affected_area"] in ("auth", "payments"):
        decision = rule("High", "P1", "Auth/Payment issue")
    elif is_cosmetic(analysis, report):
        decision = rule("Low", "P3", "UI cosmetic")
    else:
        decision = llm_triage(report, analysis)   # ambiguous fallback

    # 2. Deterministic team lookup
    team = teams.find_team_for_area(analysis["affected_area"])

    # 3. Tool-driven assignee selection by the Triage Agent
    #    Agent is given get_team_members + get_developer_history tools
    #    (see §5.7) plus the derived open-load map for `team`.
    assignee = triage_agent.run(
        analysis=analysis,
        priority=decision.priority,
        team_id=team.id,
        deps=TriageDeps(teams=teams, tasks=tasks,
                        open_load=open_tasks_per_dev(tasks, team)),
    )

    # 4. Deterministic notification list
    notify = build_notify_list(team, decision.priority)

    return {**decision, "team": team.name,
            "suggested_assignee": assignee, "notify": notify}
```

**Helpers (keyword + heuristic):**
- `is_production_outage`: keywords `outage`, `down`, `cannot access`, `all users`, `500`, `502`, `503` + environment = production.
- `is_cosmetic`: keywords `alignment`, `color`, `typo`, `padding`, `spacing` AND no functional verbs like `cannot`, `fails`, `crashes`.
- `build_notify_list`: the rule in §5.6.
- `open_tasks_per_dev`: derived current-load map from §5.8.
- **Fallback scorer:** if the configured Triage model does not support
  tool calling, `triage_agent.run(...)` is replaced by the previous
  deterministic skills-only scorer (`skills ∩ tokens` + on-call + seniority
  tie-break). Kept as a code path so the system degrades gracefully.

---

## 8. Orchestration

### 8.1 Tech Choices (pick one stack)

| Stack | Good for |
|---|---|
| **n8n / Make.com** | No-code demo, fast to wire up form → agents → Jira |
| **LangGraph / LangChain** | Code-first, full control, easy to add memory/branching |
| **Anthropic SDK + plain Python/Node** | Minimal dependencies, easiest to test, recommended for a coding-assessment style project |

A minimal Node/Python implementation is ~200 lines: one HTTP endpoint, two model calls in sequence, one rules module, one team-config loader.

### 8.2 Error Handling

- LLM returns invalid JSON → retry once with a stricter "JSON only" reminder; on second failure, fall back to a safe default (`status: Needs More Information`).
- Agent 1 fails → skip to a degraded path that only runs deterministic rules.
- Agent 2 fails → return Agent 1's analysis to the user with a "manual triage required" flag.
- `teams.json` invalid at boot → fail fast with a clear error; do not start the server.

### 8.3 Observability

Log per request: input hash, agent latencies, token usage, rule applied (or LLM fallback), final severity/priority, `assignee_id`, `selection_score`, and the resolved `notify` ids. Enables later evaluation of how often rules vs LLM drive decisions and whether assignment is balanced across the team.

---

## 9. Final Output (User-Facing)

```json
{
  "bug_id": "BUG-2026-0142",
  "summary": "Checkout fails with HTTP 500 when applying a discount code on Safari.",
  "severity": "High",
  "priority": "P1",
  "status": "Triaged",
  "missing_information": [
    "Exact discount code that triggers the failure",
    "Whether the issue reproduces on other browsers"
  ],
  "suggested_repro_steps": [
    "Add any item to the cart",
    "Proceed to checkout",
    "Enter a discount code in the promo field",
    "Click 'Apply'"
  ],
  "suggested_owner_team": "Billing Team",
  "suggested_assignee": {
    "id": "dev-alice",
    "name": "Alice Chen",
    "reason": "Matched skills: stripe, payments. On-call. Senior."
  },
  "notify": [
    {"id": "pm-dana", "name": "Dana Park", "role": "product_manager"},
    {"id": "tl-carol", "name": "Carol Lee", "role": "tech_lead"}
  ],
  "triage_recommendation": "Assign to Alice Chen (Billing). Discount-code path on Safari is broken; treat as P1.",
  "rule_applied": "Payment issue → High / P1",
  "artifacts": {
    "jira_ticket": "...",
    "test_cases": ["...", "..."],
    "duplicate_check_query": "\"discount\" AND \"Safari\" AND \"500\"",
    "handoff_note": "..."
  }
}
```

---

## 10. Acceptance Criteria — How This Design Satisfies Each

| Criterion | Where it's handled |
|---|---|
| User can submit a bug report | §3 — Input schema + form/API endpoint |
| System classifies severity and priority | §5 — Triage Agent + §7 rules |
| System suggests reproduction steps | §4 — `inferred_repro_steps` |
| System flags missing information | §4 — `missing_information` array + `completeness.verdict`, enforced by the Completeness Gate in §4.4 *before* triage runs |
| System recommends owner team and assignee | §5.4 + §5.6 — `teams.json` lookup + skill-scored assignee |
| System notifies the right stakeholders | §5.6 — `notify_on` per priority + escalation contact |
| At least 2 agents clearly involved | §4 and §5 — Analyzer + Triage, distinct prompts and outputs |

---

## 11. Suggested Build Order

1. **Skeleton orchestrator + input validation** — no LLM yet, returns echo.
2. **Agent 1 (Analyzer)** with 5 fixture bug reports for testing — must emit `completeness` on every output.
3. **Completeness Gate** (§4.4) — orchestrator branches on `analysis.completeness.verdict`. Unit tests with fixture analyses for both branches; assert Triage Agent is never invoked when verdict is `needs_more_info`.
4. **Deterministic rules module** (§7) with unit tests for each rule row.
5. **`teams.json` + `tasks.json` loaders + Pydantic validators** (`TeamsConfig`, `TasksConfig`) with fixture files. Cross-validate that every `task.assignee_id` resolves to a developer.
6. **Tool implementations** — `get_team_members` (§5.7 Tool 1) and `get_developer_history` (§5.7 Tool 2), with unit tests over the fixtures covering: missing team, missing developer, `area` filter, `since_days` window, `include_unavailable` flag.
7. **Deterministic fallback scorer** — kept around for model-capability fallback (§7). Unit-test against a few `(analysis, priority) → expected_assignee_id` cases.
8. **Agent 2 (Triage)** — wired to the deterministic rules module *and* the two tools. Prompt enforces the tool-use protocol from §5.7 ("call get_team_members once, get_developer_history up to 3 times, cite ids in the reason"). Tool-call budget enforced by the orchestrator.
9. **End-to-end flow** with simple HTML form or CLI input.
10. **Agent 3 (Artifacts)** — Jira format, test cases, handoff note, using `team.jira_project` / `team.slack_channel` and the chosen `suggested_assignee`.
11. **Polish:** logging (tool calls in/out, budget exceeded, fallback triggered, gate short-circuits), retries, evaluation harness over the fixture set.

---

## 12. Evaluation Approach

Build a fixture set of ~20 bug reports labeled with the expected severity, priority, team, and assignee. Run the workflow nightly (or per PR) and measure:

- % of fixtures where severity matches.
- % where priority matches.
- % where the suggested team matches.
- % where the suggested **assignee** matches.
- % where `missing_information` correctly flags omitted fields.
- Distribution of assignments across the team — flag if any one developer gets > 50% of P1+ tickets in the fixture set, which usually signals a skills-tag gap.
- **Tool-use hygiene** (§5.7): % of runs that stay within the tool-call budget; % where `suggested_assignee.reason` cites at least one task id returned by `get_developer_history`; % that fall back to the deterministic scorer (high values here signal the chosen model doesn't reliably support tool calling).

This makes the system tunable rather than vibes-based, and gives a clear signal when a prompt change or a `teams.json` / `tasks.json` edit regresses behavior.
