# CV Screener

Multi-agent CV screening built on **Pydantic AI** with **Together AI** as the LLM
backend. Screens a candidate's CV against a job description by running eight
agents — a CV parser, a JD parser, five specialists (skills, experience,
education, red flags, communication) in parallel, and an aggregator that
produces the final hiring recommendation. Ships with a CLI and a small web UI
that visualises the pipeline live, persists every run to SQLite, and lets you
chat with any past result.

See [docs/design.md](docs/design.md) for the pipeline diagram and per-agent
contracts.

---

## Prerequisites

- **Python 3.10+** (project tested on 3.12)
- A **Together AI** API key — sign up at <https://together.ai>

---

## Install

```bash
# 1. Create a virtualenv
python3.12 -m venv .venv

# 2. Install the package in editable mode
.venv/bin/pip install -e .
```

Activate the venv if you'd rather not type `.venv/bin/...` every time:

```bash
source .venv/bin/activate
```

---

## Configure

Copy the example env file and fill in your secrets:

```bash
cp .env.example .env
```

Then edit [.env](.env):

```dotenv
# REQUIRED — Together AI key for all LLM calls
TOGETHER_API_KEY=tgp_v1_...

# REQUIRED for the web UI — login credentials
CV_SCREENER_USERNAME=admin
CV_SCREENER_PASSWORD=changeme

# OPTIONAL — persist session cookies across server restarts
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
# CV_SCREENER_SECRET_KEY=

# OPTIONAL — override the model used per agent role.
# Default for all three roles is openai/gpt-oss-20b.
# CV_SCREENER_MODEL_PARSER=openai/gpt-oss-20b
# CV_SCREENER_MODEL_SPECIALIST=openai/gpt-oss-20b
# CV_SCREENER_MODEL_AGGREGATOR=openai/gpt-oss-20b
# CV_SCREENER_MODEL_CHAT=openai/gpt-oss-20b
```

> The web UI **refuses to log you in** if `CV_SCREENER_PASSWORD` is unset — the
> server returns a clear error rather than running unauthenticated.

---

## Run

### Web UI (recommended)

```bash
.venv/bin/cv-screener serve
# defaults: 127.0.0.1:8000
```

Open <http://127.0.0.1:8000/> in your browser, sign in with the credentials
from `.env`. You get:

- **Setup view** — paste CV + JD into the two textareas (or click "Load
  example" to use the bundled candidate).
- **Pipeline view** (entered on Run) — eight agent cards arranged in three
  stages with animated connectors; click any card after it completes to
  inspect its raw input prompt and typed output.
- **Result view** — final score, recommendation badge, strengths/concerns,
  suggested interview questions, full rationale.
- **History sidebar** — every screening is saved to `runs.db`; click an entry
  to reload it.
- **Chat popup** (bottom-right) — ask follow-up questions about any loaded
  run; the assistant has the full screening data as context.

Bind to a different host/port:

```bash
.venv/bin/cv-screener serve --host 0.0.0.0 --port 9000
```

> If you expose the UI beyond localhost, change `CV_SCREENER_PASSWORD` and
> consider a reverse proxy with TLS (Tailscale, Cloudflare Access, nginx etc).

### CLI (one-shot, no server)

```bash
.venv/bin/cv-screener run \
  --cv examples/cv_example.txt \
  --jd examples/jd_example.md
```

Options:

- `--out path.json` — also write the full structured result (parsed CV+JD, all
  five specialist outputs, recommendation) to a file
- `--verbose` — print every specialist's output to stdout, not just the final
  recommendation

### As a library

```python
import asyncio
from cv_screener import screen

raw_cv = open("examples/cv_example.txt").read()
raw_jd = open("examples/jd_example.md").read()
result = asyncio.run(screen(raw_cv, raw_jd))

print(result.recommendation.recommendation)  # 'strong_yes' | 'yes' | 'maybe' | 'no'
print(result.recommendation.overall_score)
print(result.skills.matched)                 # list[str]
```

`result` is a `ScreeningResult` dataclass with typed fields for each agent
output — see [src/cv_screener/models.py](src/cv_screener/models.py).

---

## Project layout

```
src/cv_screener/
  models.py            # Pydantic contracts for every agent (parser → aggregator)
  pipeline.py          # screen() — CLI / library entrypoint
  pipeline_events.py   # screen_events() — async generator yielding live agent events
  cli.py               # `cv-screener run` and `cv-screener serve` commands
  server.py            # FastAPI app: /login, /screen, /runs, /runs/{id}/chat
  auth.py              # Login page + session middleware helpers
  db.py                # SQLite schema + queries (runs + chat_messages)
  chat.py              # Per-run chat agent (full context, streaming reply)
  agents/
    _factory.py        # Together-backed model routing per role
    parser.py          # cv_parser_agent + jd_parser_agent → ParsedCV / JobDescription
    skills.py          # → SkillsMatch
    experience.py      # → ExperienceEvaluation
    education.py       # → EducationEvaluation
    red_flags.py       # → RedFlagReport
    communication.py   # → CommunicationEvaluation
    aggregator.py      # → Recommendation
  static/index.html    # Single-page visualiser (history sidebar, chat popup, two views)
examples/
  cv_example.txt
  jd_example.md
docs/
  design.md            # Architecture diagram + agent contracts
runs.db                # Created on first server run; override with CV_SCREENER_DB=...
```

---

## How the pipeline runs

```
            ┌────────────────────┐
            │  CV parser   JD parser   │  Stage 1 — parse (parallel)
            └────────────────────┘
                       │
   ┌──────┬──────┬──────┼──────┬──────┐
 Skills  Exp  Edu   Red flags  Communication   Stage 2 — specialists (parallel)
   └──────┴──────┴──────┼──────┴──────┘
                       │
                  Aggregator                     Stage 3 — reduce
                       │
                 Recommendation
```

- **Stage 1 + Stage 2** use `asyncio.gather`, so the wall-clock for each stage
  is `max()` not `sum()`. A full screening of the bundled example takes ~30 s
  end-to-end on the default `openai/gpt-oss-20b` model and uses ~12 k tokens.
- **Every payload between agents is a Pydantic model** — no free-form strings
  cross agent boundaries except the parser's raw input and the aggregator's
  final `rationale`.
- **Per-run state and per-message chat history** are persisted to SQLite so
  the history sidebar and chat popup survive restarts and page reloads.

---

## Troubleshooting

**`TOGETHER_API_KEY is not set`** — your `.env` is missing or the key isn't
populated. Confirm with `cat .env` and re-run.

**Login page returns "Server not configured: set CV_SCREENER_PASSWORD"** —
add `CV_SCREENER_PASSWORD=...` to `.env` and restart `cv-screener serve`.

**Sessions don't survive a server restart** — set `CV_SCREENER_SECRET_KEY` in
`.env` (any random string ≥ 32 chars).

**Want a different SQLite location** — `CV_SCREENER_DB=/path/to/runs.db
cv-screener serve`.

**Want to delete a run from history** — `DELETE /runs/{id}` (no UI button
yet); or `rm runs.db` to wipe everything.

---

## License

This project is for internal use; see the source for details.
