# Bug Triage AI Workflow

A multi-agent workflow that ingests raw bug reports and produces structured
triage decisions — severity, priority, owner team, suggested assignee, and
downstream artifacts (Jira ticket, test cases, handoff note). Reduces manual
triage time, enforces consistent severity/priority rules, and flags
incomplete reports before they reach engineers.

> **Status:** design phase. The full architecture, schemas, and build order
> live in [docs/bug_triage_design.md](docs/bug_triage_design.md). Code in
> `src/` is scaffolding only; implementation tracks §11 of the design doc.

---

## Architecture at a glance

```
Bug Report
    │
    ▼
Orchestrator ── validates input, loads teams.json + tasks.json
    │
    ▼
Agent 1 — Bug Analyzer
  • Summary, affected area, missing info
  • Inferred repro steps, extracted errors
  • completeness verdict
    │
    ▼
Completeness Gate (orchestrator)
  • needs_more_info  → short-circuit (Triage NOT invoked)
  • complete         → continue
    │
    ▼
Agent 2 — Triage Agent
  • Deterministic severity/priority rules first; LLM only for residuals
  • Tools: get_team_members, get_developer_history
  • Picks assignee from evidence (skills + actual task history)
    │
    ▼
Agent 3 (stretch) — Artifact Generator
  • Jira ticket, test cases, duplicate query, handoff note
    │
    ▼
Final Report
```

Key design choices, each detailed in the design doc:

- **Two agents, not one** — separation between *understanding* the bug
  (Analyzer) and *deciding what to do with it* (Triage). Independently
  testable; lets Triage use a stronger / tool-calling model.
- **Completeness gate is in the orchestrator, not in Triage.** Incomplete
  reports never reach the more expensive triage path. See §4.4.
- **Rules-first severity/priority.** Deterministic table in §5.3; the LLM
  only handles residual cases.
- **Tool-driven assignee selection.** Triage calls `get_team_members(team_id)`
  and `get_developer_history(developer_id, area=...)` instead of receiving
  `teams.json` / `tasks.json` in its prompt — keeps prompts small, every
  lookup is logged, and reasons must cite specific signals (matched skills,
  task ids). See §5.7.
- **Config-driven teams and history.** `config/teams.json` (roster,
  stakeholders, notify rules) and `config/tasks.json` (historical
  assignments) — loaded once, Pydantic-validated at boot.
- **Deterministic notification list.** Built by the orchestrator from
  `stakeholder.notify_on` once Triage produces a final priority.
- **Graceful degradation.** If the configured Triage model doesn't support
  function calling, the orchestrator falls back to a skills-only scorer
  (§7, §11).

---

## Repository layout

```
docs/
  bug_triage_design.md     # Single source of truth for the system design
config/                    # (planned) teams.json + tasks.json
src/                       # (in progress) orchestrator + agents
examples/                  # fixture bug reports (planned)
pyproject.toml
```

---

## Build order

The design doc's §11 lists the recommended build order. In short:

1. Skeleton orchestrator + input validation (no LLM yet)
2. Agent 1 (Analyzer) — must emit `completeness` on every output
3. Completeness Gate with unit tests for both branches
4. Deterministic rules module (§7)
5. `teams.json` + `tasks.json` Pydantic loaders + cross-validation
6. Tool implementations (`get_team_members`, `get_developer_history`)
7. Deterministic fallback scorer (for non-tool-calling models)
8. Agent 2 (Triage) wired to rules + tools, with tool-call budget enforced
9. End-to-end flow (HTML form or CLI)
10. Agent 3 (Artifacts) — Jira ticket, test cases, handoff note
11. Polish: logging, retries, evaluation harness

---

## Evaluation

Per §12 of the design: a fixture set of ~20 labeled bug reports, scored on
severity match, priority match, team match, assignee match,
`missing_information` accuracy, assignment distribution across the team,
and tool-use hygiene (within budget, reasons cite tool output, fallback
rate).

---

## References

- Design doc: [docs/bug_triage_design.md](docs/bug_triage_design.md) — read
  this first. Everything below the surface (schemas, prompts, tool
  signatures, error handling, observability) lives there.
