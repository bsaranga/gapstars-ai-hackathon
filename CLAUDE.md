# CLAUDE.md

Guidance for Claude when extending this repo into a **new domain**. The current
implementation screens CVs against job descriptions, but the entire
architecture is generic: a *parser fan-in → specialist fan-out → aggregator
reduce* pipeline of typed Pydantic-AI agents. Re-targeting it is mostly a
matter of swapping the Pydantic models and prompts; the wiring stays the same.

---

## 1. The framework: Pydantic AI

This project uses **Pydantic AI** (`pydantic-ai>=0.0.20`) — a thin agent
framework whose value proposition is:

- **Typed I/O**: every `Agent` is constructed with an `output_type` that is a
  Pydantic model. Pydantic AI validates the LLM response against the schema
  and retries on failure (`retries=2` in `_factory.py`).
- **Model-agnostic**: agents are built against a `Model` abstraction. Here we
  use `OpenAIChatModel` with an `OpenAIProvider` pointed at Together AI's
  OpenAI-compatible endpoint. Swapping providers means changing only the
  `base_url` / `api_key` / `model_name` in `_factory.py`.
- **Async-first**: `agent.run(prompt)` is awaitable, which is what makes the
  fan-out via `asyncio.gather` cheap.
- **Result object** exposes `.output` (the validated Pydantic model) and
  `.usage()` (token counts) — both are used in `pipeline_events.py`.

### Anatomy of an agent (canonical pattern in this repo)

```python
# src/cv_screener/agents/<role>.py
from ..models import SomeOutputModel
from ._factory import make_agent

_PROMPT = """System prompt: what the agent does, what JSON shape its input
has, and explicit rules for each output field including scoring rubrics."""

some_agent = make_agent(
    "specialist",                  # role → picks model from env
    output_type=SomeOutputModel,   # Pydantic class; defines JSON shape
    system_prompt=_PROMPT,
)
```

That's the entire shape of every agent in this codebase. No tools, no
multi-turn loops, no agent-to-agent calls — each agent is a single
`prompt → typed-output` function. Agent composition happens in
`pipeline.py`, not inside the agents.

### Things Pydantic AI can do that this repo does *not* use

When extending, know your options before adding scaffolding:

- **Tool calling** (`@agent.tool`): give an agent callable Python functions.
  Not needed here because the orchestration is deterministic — the pipeline,
  not the LLM, decides what runs next.
- **Dependency injection** (`deps_type=`): pass typed context (DB handles,
  API clients) into tools. Add this if a specialist needs to look something
  up at runtime.
- **Streaming output** (`agent.run_stream`): we stream *between* agents at
  the pipeline level (`screen_events`), but each agent's own response is
  awaited as a whole.
- **Message history**: we manually build OpenAI-style history in `chat.py`
  using the raw `AsyncOpenAI` client instead of going through Pydantic AI.
  This is deliberate — the chat agent is free-form text, so the typed-output
  guarantee of Pydantic AI brings no value there.

---

## 2. The architectural pattern: Parse → Fan-out → Reduce

```
Stage 1 (parse, parallel)   Stage 2 (specialists, parallel)   Stage 3 (reduce)
┌───────────────┐            ┌──────────────┐
│ Input A parser├──ParsedA──┐│ Specialist 1 ├──Typed1──┐
└───────────────┘           ││ Specialist 2 ├──Typed2──┤
                            ├┤ Specialist 3 ├──Typed3──┼──► Aggregator ──► FinalRec
┌───────────────┐           ││ Specialist 4 ├──Typed4──┤
│ Input B parser├──ParsedB──┘│ Specialist 5 ├──Typed5──┘
└───────────────┘            └──────────────┘
```

Implemented in `src/cv_screener/pipeline.py`. Two structural rules carry the
whole design:

1. **Specialists are orthogonal and never call each other.** Each one
   answers exactly one narrow question and emits exactly one Pydantic model.
   This is what makes `asyncio.gather` safe — wall-clock is `max()` not
   `sum()`.
2. **The aggregator is reductive only.** It never re-reads the raw input;
   it only reasons over the typed specialist outputs plus the original
   structured request. This keeps the final step cheap and auditable.

### Why this pattern works well with Pydantic AI

- Typed boundaries between agents mean the aggregator's prompt receives a
  predictable JSON shape — no fragile string parsing.
- Adding a sixth specialist is a 3-line change: write the agent, add it to
  the `asyncio.gather`, extend the aggregator's input dict. **Only add one
  if its judgement is not already a slice of an existing specialist** —
  keep the set orthogonal.
- Failures are localised: if one specialist throws, you see exactly which
  one in `pipeline_events.py` via the `failed` event.

### When this pattern is the wrong fit

- **Task requires iterative reasoning** (agent decides what to do next
  based on prior outputs) → use Pydantic AI tools + a single agent with
  a controller loop instead.
- **Inputs depend on each other** (specialist B needs specialist A's
  output) → either merge them into one agent, or restructure into stages.
- **Output is open-ended prose** (a written report) → typed outputs add
  friction with no benefit; use the raw `AsyncOpenAI` client like `chat.py`
  does.

---

## 3. Model routing

`src/cv_screener/agents/_factory.py` is the single place model selection
happens. Three roles, three env vars, one default:

| Role         | Env var                          | Used for                          |
|--------------|----------------------------------|-----------------------------------|
| `parser`     | `CV_SCREENER_MODEL_PARSER`       | structured extraction (JSON-strict)|
| `specialist` | `CV_SCREENER_MODEL_SPECIALIST`   | the five parallel judgement agents |
| `aggregator` | `CV_SCREENER_MODEL_AGGREGATOR`   | final reductive synthesis (often stronger) |

Default for all three: `openai/gpt-oss-20b` on Together AI.

When re-purposing, **keep the three-role split** even if you start with one
model everywhere — it gives you a free lever to upgrade only the aggregator
(or only the parser) without touching code. Rename the env-var prefix to
match the new domain.

The chat endpoint (`chat.py`) uses a separate `CV_SCREENER_MODEL_CHAT` env
var and falls back to the aggregator model.

---

## 4. Layout (with re-purposing notes)

```
src/cv_screener/
  models.py            # ALL Pydantic contracts — start your port here
  agents/
    _factory.py        # Model routing; rename env-var prefix
    parser.py          # 1+ structured-extraction agents
    <specialist>.py    # one file per orthogonal specialist
    aggregator.py      # reductive synthesiser
  pipeline.py          # screen(): orchestrates parse → fan-out → reduce
  pipeline_events.py   # same, but yields per-agent events for the UI
  cli.py               # typer CLI: `run` (one-shot) + `serve` (web UI)
  server.py            # FastAPI: /login, /screen (NDJSON stream), /runs, /chat
  chat.py              # Free-form chat over a saved run (raw OpenAI client)
  auth.py              # Session-cookie login (single shared password)
  db.py                # SQLite schema for runs + chat history
  static/index.html    # SPA visualiser
```

`pipeline.py` vs `pipeline_events.py`: the former returns a single
`ScreeningResult` (used by CLI and the library entrypoint); the latter is an
async generator that yields `start` / `done` / `failed` events per agent
plus `pipeline_done` (used by the FastAPI streaming endpoint). Both call the
exact same agents — only the orchestration loop differs.

---

## 5. Re-purposing checklist

To target a new domain (e.g. "screen research papers against a review
checklist", "evaluate PRs against code-quality criteria", "audit contracts
against legal requirements"):

1. **Define the contracts in `models.py`.** Replace `ParsedCV`,
   `JobDescription`, the five specialist outputs and `Recommendation` with
   the new domain's types. Keep the *shape*: structured-input models,
   one-per-specialist output models, one final reductive model.
2. **Choose your specialists.** Pick 3–6 orthogonal axes of judgement.
   If two overlap, merge them. If one is a slice of another, drop it.
3. **Write each agent file.** Copy the pattern from
   `agents/skills.py` (~25 lines): import the output model, write the
   system prompt with explicit rules and scoring rubrics, call
   `make_agent("specialist", output_type=..., system_prompt=...)`.
4. **Rewire `pipeline.py`.** Update the two `asyncio.gather` calls and the
   `agg_payload` dict. The `_payload` helper assumes a CV+JD pair — adjust
   the keys to your inputs.
5. **Mirror changes in `pipeline_events.py`** (same agents, same fan-out).
6. **Update the aggregator prompt** in `aggregator.py` with the new
   weighting rubric and the new recommendation enum.
7. **Update the CLI flags** in `cli.py` (`--cv`, `--jd` → your inputs).
8. **Update `chat.py`'s `_SYSTEM_TMPL`** so the chat agent sees the new
   structured run in its system prompt.
9. **Rename env vars** (`CV_SCREENER_*` → `<NEW_DOMAIN>_*`) and the
   package directory if you want — nothing else depends on the name.
10. **Update `static/index.html`** if you want different agent cards in the
    visualiser; the NDJSON event stream from `/screen` is generic.

Things you almost never need to change:
- `_factory.py` (unless changing LLM provider)
- `db.py` schema (runs are stored as opaque JSON)
- `auth.py`, `server.py` routing
- The `asyncio.gather` orchestration shape itself

---

## 6. Conventions worth keeping

- **Every cross-agent payload is JSON of Pydantic `.model_dump()` output.**
  No free-form strings between agents except (a) the parser's raw input
  and (b) the aggregator's final `rationale` field.
- **Prompts live next to the agent they configure.** Don't centralise them
  — they're part of the agent's contract, not shared config.
- **Prompts state the input shape explicitly** ("You receive a JSON object
  with keys 'cv' and 'jd'…"). This dramatically improves reliability of
  structured-output models.
- **Scoring rubrics are numeric and explicit** in the prompt (e.g.
  "missing one required skill drops the score ~15–25"). Vague rubrics
  produce vague scores.
- **One specialist deliberately sees less than the others.** The red-flag
  agent never sees the JD so it stays objective; the communication agent
  judges writing quality, not content fit. Decide deliberately what each
  specialist can and cannot see — it shapes their bias.
- **`from __future__ import annotations`** at the top of every module —
  required for the `str | None` style used in the Pydantic models on 3.10.

---

## 7. Running

```bash
.venv/bin/cv-screener run --cv examples/cv_example.txt --jd examples/jd_example.md
.venv/bin/cv-screener serve   # web UI on :8000
```

Library use:

```python
import asyncio
from cv_screener import screen
result = asyncio.run(screen(raw_cv, raw_jd))   # → ScreeningResult dataclass
```

Required env: `TOGETHER_API_KEY`. For the web UI also
`CV_SCREENER_USERNAME` / `CV_SCREENER_PASSWORD`. See `README.md` for the
full list.

---

## 8. Extending: tools, streaming, message history

The repo currently uses Pydantic AI in its simplest mode (one prompt → one
typed output, no tools, no history). Below are concrete, idiomatic patterns
for the three planned extensions, taken from the Pydantic AI docs, with
guidance on where they slot into *this* codebase.

### 8.1 Tools — letting an agent call Python functions

**When to add tools.** When a specialist needs runtime data the prompt
can't carry — e.g. looking a candidate up in an ATS, querying a vector
store of past hires, fetching a JD revision history, hitting a calculator
for years-of-experience math. If the data is already in the input payload,
don't add a tool; pass it directly.

**Two decorator forms.** `@agent.tool_plain` for context-free helpers,
`@agent.tool` for tools that need `RunContext` (deps, usage, model info).

```python
from pydantic_ai import Agent, RunContext

agent = Agent(
    model=_together_model("specialist"),
    output_type=SkillsMatch,
    deps_type=AtsClient,           # injected per-run
    system_prompt=_PROMPT,
)

@agent.tool_plain
def normalise_skill(name: str) -> str:
    """Canonicalise a skill name (k8s → kubernetes)."""
    return _SKILL_ALIASES.get(name.lower(), name.lower())

@agent.tool
async def lookup_past_role(ctx: RunContext[AtsClient], company: str) -> dict:
    """Fetch verified tenure data for a company from the ATS."""
    return await ctx.deps.fetch_tenure(company)
```

**Wiring into `_factory.py`.** Add an optional `deps_type` parameter to
`make_agent`, then pass `deps=...` at call sites:

```python
def make_agent(role, *, output_type, system_prompt, deps_type=None):
    return Agent(
        model=_together_model(role),
        output_type=output_type,
        system_prompt=system_prompt,
        deps_type=deps_type,
        retries=2,
    )

# In pipeline.py
result = await skills_agent.run(payload, deps=ats_client)
```

**Caveats.**
- Tool calls add round-trips. A specialist that previously cost one LLM
  call may now cost N+1. Keep tools narrow and idempotent.
- The Together-hosted model must support OpenAI-style function calling.
  `openai/gpt-oss-20b` (the current default) is borderline; pick a model
  with reliable tool support (e.g. a Llama-3.1-70B-Instruct variant) for
  any agent that gets tools.
- Tools break the "specialists are independent" invariant *only* if the
  tool reaches into another specialist's output. Don't do that — keep
  each specialist's tool surface its own.

### 8.2 Streaming — incremental output from an agent

Today `pipeline_events.py` streams *between* agents (one event per agent
start/done). Pydantic AI also supports streaming *within* an agent, which
is what you want for: live-updating the aggregator's `rationale` as it
writes, or streaming the chat reply (currently done with raw
`AsyncOpenAI`).

**Streaming text** (use for free-form fields):

```python
async with agent.run_stream(prompt) as response:
    async for chunk in response.stream_text(delta=True):
        await queue.put({"type": "delta", "agent": name, "text": chunk})
    final = await response.get_output()   # validated Pydantic model
```

`delta=True` yields only the new text per chunk; `delta=False` (default)
yields the accumulated string. Pass `debounce_by=None` to disable the
0.1s coalescing if you want every token.

**Streaming structured output** (use for typed fields as they validate):

```python
async with agent.run_stream(prompt) as response:
    async for partial in response.stream_output():
        # partial is a partially-filled instance of output_type
        await queue.put({"type": "partial", "agent": name,
                         "output": partial.model_dump(exclude_unset=True)})
```

**Streaming raw events** (use when you want tool calls *and* text):

```python
async with agent.run_stream_events(prompt) as stream:
    async for event in stream:
        # event is a typed AgentStreamEvent — text delta, tool call, etc.
        ...
```

**Wiring into this repo.**
- Replace `agent.run(...)` in `pipeline_events.py::_run_one` with
  `run_stream(...)` and emit `partial` events alongside the existing
  `start` / `done`. The FastAPI `/screen` endpoint is already an NDJSON
  stream — it just needs the new event types forwarded.
- Replace the hand-rolled `AsyncOpenAI` streaming in `chat.py` with a
  Pydantic AI agent + `run_stream` once chat needs structured output or
  tool calls. If chat stays free-form prose with no tools, the current
  raw-OpenAI path is simpler — don't migrate for its own sake.
- The frontend (`static/index.html`) consumes NDJSON line-by-line, so
  new event types are additive.

### 8.3 Message / chat history — multi-turn agents

Today `chat.py` builds an OpenAI-style `messages=[...]` list by hand,
storing rows in SQLite (`db.get_chat_messages`). Pydantic AI has
first-class history support that gives you typed messages, tool-call
records, and a serializer.

**Single-agent multi-turn:**

```python
result1 = await agent.run("First question")
result2 = await agent.run("Follow-up", message_history=result1.new_messages())
```

- `result.new_messages()` → messages produced by *this* run only.
- `result.all_messages()` → full history including everything passed in.
- JSON variants: `new_messages_json()` / `all_messages_json()`.
- **If `message_history` is non-empty, Pydantic AI skips re-injecting the
  system prompt** — it assumes your history already starts with one.

**Persisting across processes** (this is what replaces the
`db.add_chat_message` + manual rebuild in `chat.py`):

```python
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_core import to_jsonable_python

# Save after each turn
db.save_history(run_id, to_jsonable_python(result.all_messages()))

# Load before next turn
raw = db.load_history(run_id)
history = ModelMessagesTypeAdapter.validate_python(raw)
result = await chat_agent.run(user_msg, message_history=history)
```

Schema change in `db.py`: replace the `chat_messages(role, content)` rows
with a single `chat_history_json` blob per run, or keep the per-row table
for UI rendering and additionally store the typed blob for replay into
Pydantic AI.

**Trimming long histories** with `history_processors`:

```python
def keep_recent(messages):
    return messages[-20:] if len(messages) > 20 else messages

chat_agent = Agent(
    model=_together_model("aggregator"),
    output_type=str,
    system_prompt=_CHAT_SYSTEM,
    history_processors=[keep_recent],
)
```

Processors can be async and can take a `RunContext` argument, so you can
do token-budget-aware trimming. They run before *every* request, so keep
them cheap.

**Wiring into this repo.**
1. Create `chat_agent = make_agent("aggregator", output_type=str, ...)` in
   a new `agents/chat.py` — drop the raw `AsyncOpenAI` client from
   `chat.py`.
2. Move the giant `_SYSTEM_TMPL` (the run summary) into the system prompt
   *only on the first turn*; subsequent turns rely on
   `message_history` so you don't pay to re-send the run context every
   call.
3. In `server.py::chat_endpoint`, replace the manual history rebuild with
   `ModelMessagesTypeAdapter.validate_python(db.load_history(run_id))`,
   then call `chat_agent.run_stream(user_msg, message_history=history)`
   and persist `result.all_messages()` after the stream completes.

### 8.4 Combining all three

A realistic extended chat agent ends up like this:

```python
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessagesTypeAdapter

chat_agent = Agent(
    model=_together_model("aggregator"),
    deps_type=RunContextDeps,                 # db handle, run record
    output_type=str,
    system_prompt=_CHAT_SYSTEM,
    history_processors=[keep_recent],
    retries=2,
)

@chat_agent.tool
async def fetch_specialist_output(
    ctx: RunContext[RunContextDeps], name: str
) -> dict:
    """Pull a specialist's raw output (skills/experience/...) on demand."""
    return ctx.deps.run["agents"][name]["output"]

async def chat_turn(run_id: int, user_msg: str):
    history = ModelMessagesTypeAdapter.validate_python(db.load_history(run_id))
    deps = RunContextDeps(run=db.get_run(run_id))
    async with chat_agent.run_stream(
        user_msg, message_history=history, deps=deps
    ) as response:
        async for chunk in response.stream_text(delta=True):
            yield chunk
        final = await response.get_output()
    db.save_history(run_id, to_jsonable_python(
        (await response.get_result()).all_messages()
    ))
```

This pattern — typed deps + tools for on-demand data + streaming text +
persisted message history — is the canonical "extended chat agent" shape
in Pydantic AI. Keep it for the chat endpoint; **do not** add tools or
history to the specialists (they're one-shot by design and adding state
breaks their parallelism).

---

## Sources

- [Pydantic AI — Tools](https://pydantic.dev/docs/ai/tools-toolsets/tools/)
- [Pydantic AI — Message History](https://pydantic.dev/docs/ai/core-concepts/message-history/)
- [Pydantic AI — Streaming (DeepWiki)](https://deepwiki.com/pydantic/pydantic-ai/4.1-streaming-and-real-time-processing)
- [Pydantic AI — Agents API](https://ai.pydantic.dev/api/agent/)
