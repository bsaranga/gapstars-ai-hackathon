"""Versioned prompt loader.

Layout:
    src/bug_triage/prompts/<role>/v<N>.md

Resolution order for a given role:
    1. Explicit `version=` argument to `load_prompt(...)`.
    2. Env var `BUG_TRIAGE_PROMPT_<ROLE_UPPER>` (e.g. `..._ANALYZER=v2`).
    3. Highest-numbered `vN.md` file in the role's folder.

Versions are integers prefixed with `v` — `v1`, `v2`, `v10`. Sorting is
numeric, not lexicographic, so `v10` correctly outranks `v2`.

Each prompt file may start with a YAML-style front-matter block separated
by `---` lines (description, author, tags, …). We currently use it only
for human-readable provenance; the loader strips it before returning the
prompt body. If you ever want runtime metadata, parse it here.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_VERSION_RE = re.compile(r"^v(\d+)$")


def _available_versions(role: str) -> list[str]:
    folder = _DIR / role
    if not folder.is_dir():
        return []
    versions: list[tuple[int, str]] = []
    for p in folder.glob("v*.md"):
        m = _VERSION_RE.match(p.stem)
        if m:
            versions.append((int(m.group(1)), p.stem))
    versions.sort()
    return [v for _, v in versions]


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + 4 :].lstrip("\n")


def load_prompt(role: str, version: str | None = None) -> tuple[str, str]:
    """Load a prompt by role.

    Returns ``(prompt_body, version)`` — the version is useful for logging
    so you can correlate runs with the exact prompt used.
    """
    if version is None:
        version = os.getenv(f"BUG_TRIAGE_PROMPT_{role.upper()}")
    available = _available_versions(role)
    if not available:
        raise FileNotFoundError(f"no prompt versions found for role={role!r}")
    if version is None:
        version = available[-1]
    if version not in available:
        raise FileNotFoundError(
            f"prompt {role}/{version}.md not found "
            f"(available: {', '.join(available)})"
        )
    body = (_DIR / role / f"{version}.md").read_text(encoding="utf-8")
    return _strip_frontmatter(body), version


__all__ = ["load_prompt"]
