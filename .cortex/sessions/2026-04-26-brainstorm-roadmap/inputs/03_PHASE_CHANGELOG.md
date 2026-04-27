# Phase 3 — Changelog Fix (DECIDE-8)

> **Mode**: `kip-engineer` for the diagnostic phase, then `roadmap-executor` for the rebuild.
> **Effort**: 2 weeks.
> **Prerequisite**: Phase 1 complete (changelog uses grounded LLM calls).
> **Parallelizable with**: Phase 2 and Phase 4.

---

## 1. Why the current changelog "doesn't work"

The user reports the existing `watch.py` + `src/changelog.py` flow "fonctionne très mal" without a precise diagnosis. **The first task of this phase is to find out why.** Likely root causes:

| Hypothesis | Evidence to look for |
|------------|----------------------|
| H1: Filesystem-watching produces noise (compile artifacts, IDE files, log files) | Many entries about `.class`, `target/`, `.idea/`, `__pycache__/` |
| H2: No git awareness — same change re-summarized across runs | Duplicate entries on consecutive days |
| H3: Verbose, low-signal LLM output | Entries are 200+ words of fluff |
| H4: Hallucinated module names | "Refactored the AuthService" when there's no AuthService |
| H5: No grouping — every file change is its own entry | Bloated daily file with 50+ tiny entries |
| H6: Breaks on large diffs (token limit) | Empty entries on commits > N files |
| H7: No delivery channel beyond file write | Team doesn't know it exists |

T-301 is the diagnostic task; T-302 onward is the rebuild informed by what we find.

---

## 2. Phase 3 deliverables

| ID | Deliverable | Lines (est.) |
|----|-------------|--------------|
| `docs/diagnostics/changelog_audit.md` | Diagnostic report from T-301 | ~100 |
| `src/temporal/git_client.py` | Git-aware indexer primitives | ~200 |
| `src/temporal/enricher.py` | Per-commit semantic summary (grounded) | ~250 |
| `src/temporal/store.py` | SQLite-backed commit log + cache | ~200 |
| `src/temporal/digest.py` | Daily/weekly digest renderer | ~200 |
| `src/temporal/channels/` | Pluggable delivery channels (file, slack, email) | ~300 |
| Rewritten `watch.py` | Git-driven, no more raw FS polling for changelog | (rewrite) |
| Updated `config.yaml` | `temporal.*` section | (modify) |
| `web/admin/changelog.html` | Browsable changelog UI | ~150 |

---

## 3. Tasks

### T-301 — Diagnose the current changelog (DON'T SKIP THIS)

**Mode**: `kip-engineer` (analytical, careful)
**Effort**: 1 day
**Depends on**: nothing.

**CONTEXT**
Before rewriting, audit. Reading the existing code + sample outputs gives us a precise list of failure modes, which becomes the acceptance criteria for the new design.

**STEPS**

1. Read `watch.py` and `src/changelog.py` (or wherever the changelog is generated). Document:
   - What triggers an entry?
   - What's the input to the LLM call?
   - What's the prompt?
   - Where is the output written?
   - What grouping/deduplication exists?
2. Sample the user's `context/changelog/` directory:
   - List all files.
   - For 5 recent files, count entries.
   - For 10 random entries, classify: useful / noise / hallucinated / verbose.
3. Run the watch loop manually for 5 minutes on the user's workspace. Note:
   - Entries triggered.
   - Latency.
   - Errors / warnings.
4. Test edge cases:
   - Touch a file without changing content (does it generate an entry?).
   - Make a 1-character change (entry?).
   - Make a 1000-line change (entry produced? truncated?).
   - Add a new file (entry?).
   - Delete a file (entry?).

**DELIVERABLE**: `docs/diagnostics/changelog_audit.md` with:
- 1-paragraph summary of how the current system works.
- Table of observed failure modes (which Hs from §1 confirmed, plus any new findings).
- 5 concrete sample entries (verbatim) with annotations.
- Recommended path: confirm the rewrite plan in §3.T-302+ or propose adjustments.

**ACCEPTANCE**
- Audit document exists and is readable.
- At least 3 failure modes are concretely identified with examples.
- Recommendations section is present.

**ANTI-PATTERNS**
- Do NOT skip this task because "we know the rewrite is needed". The diagnostics inform the acceptance tests.
- Do NOT propose features in this task — only diagnose.

---

### T-302 — Build `src/temporal/git_client.py`

**Mode**: `roadmap-executor`
**Effort**: 1 day
**Depends on**: T-301.

**CONTEXT**
Replace filesystem polling with git-driven change detection. The watch loop becomes: "since last seen commit SHA, what commits exist? for each, what files changed?"

**FILE**: `src/temporal/git_client.py`

```python
"""Git-aware primitives for the changelog system.

Wraps subprocess calls to git. No GitPython dependency to keep the install lean.

API:
    last_indexed_sha() -> str | None
    set_last_indexed_sha(sha: str)
    new_commits_since(sha: str | None) -> list[Commit]
    diff_for_commit(sha: str) -> Diff
    files_changed(sha: str) -> list[FileChange]

Where:
    Commit = NamedTuple(sha, author, date, subject, body)
    FileChange = NamedTuple(path, status, insertions, deletions)
    Diff = NamedTuple(commit, files: list[FileChange], unified_diff_text: str)
"""

import subprocess
from pathlib import Path
from typing import NamedTuple

class Commit(NamedTuple):
    sha: str
    author: str
    date: str
    subject: str
    body: str

class FileChange(NamedTuple):
    path: str
    status: str   # A | M | D | R
    insertions: int
    deletions: int

def last_indexed_sha(state_path: Path) -> str | None: ...
def set_last_indexed_sha(state_path: Path, sha: str) -> None: ...

def new_commits_since(sha: str | None, repo: Path, *, max_commits: int = 100) -> list[Commit]:
    """List commits in chronological order. If sha is None, take the last max_commits."""
    args = ["git", "-C", str(repo), "log", "--reverse", "--format=%H%x1f%an%x1f%aI%x1f%s%x1f%b%x1e"]
    if sha:
        args.append(f"{sha}..HEAD")
    else:
        args.append(f"-n{max_commits}")
    ...

def files_changed(sha: str, repo: Path) -> list[FileChange]: ...
def diff_for_commit(sha: str, repo: Path, *, max_lines: int = 5000) -> str: ...
```

**State file**: `context/temporal/state.json` — stores `last_indexed_sha`, `last_run_at`.

**ACCEPTANCE**
- `new_commits_since(None, ".")` returns the last 100 commits of the repo.
- `new_commits_since(<sha>, ".")` returns only commits after that SHA.
- `files_changed(<sha>, ".")` returns the correct file list (verify against `git show --stat`).
- `diff_for_commit(<sha>, ".", max_lines=100)` truncates and adds a `[truncated]` note.

**ANTI-PATTERNS**
- Do NOT use `git log -p` for diff retrieval — too slow for large commits. Use `git show <sha>` with caps.
- Do NOT load full commit history into memory — page if needed.

---

### T-303 — Build `src/temporal/store.py` (commit cache)

**Mode**: `roadmap-executor`
**Effort**: 1 day
**Depends on**: T-302.

**CONTEXT**
SQLite cache for enriched commit summaries. Avoids re-summarizing on every digest run.

**FILE**: `src/temporal/store.py`

```python
"""SQLite store for enriched commits.

Schema:
- commits(sha PK, author, date, subject, body, files_json,
          intent, summary, modules_affected_json, risk_score,
          enriched_at, g_version)

The 'enriched' fields are populated by enricher.py.
"""

class TemporalStore:
    def __init__(self, db_path: str | Path): ...

    def upsert_commit(self, commit: Commit, files: list[FileChange]) -> None: ...
    def is_enriched(self, sha: str) -> bool: ...
    def set_enrichment(self, sha: str, *, intent: str, summary: str,
                       modules_affected: list[str], risk_score: float,
                       g_version: str) -> None: ...

    def commits_in_range(self, since: str, until: str) -> list[dict]: ...
    def commits_for_module(self, module: str, limit: int = 50) -> list[dict]: ...
```

**ACCEPTANCE**
- Tests in `tests/test_temporal_store.py` cover upsert idempotency and range queries.

---

### T-304 — Build `src/temporal/enricher.py` (grounded commit summary)

**Mode**: `kip-engineer` (this is grounded LLM work)
**Effort**: 2 days
**Depends on**: T-303, Phase 1 grounding.

**CONTEXT**
For each new commit, produce a structured summary. **Grounded**: every module name in the summary must be in `files_changed`. Hallucinated modules → reject and retry once, then abstain.

**FILE**: `src/temporal/enricher.py`

```python
"""Per-commit semantic enrichment.

For each commit:
  Input: subject + body + files_changed list + (optional) truncated diff.
  Output: {
    intent: feature | fix | refactor | chore | docs | test | unknown,
    summary: 1-2 sentence narrative,
    modules_affected: list[str],   // grounded against files_changed
    risk_score: float in [0, 1],   // heuristic
  }

Grounded with Phase 1's GROUNDING_INSTRUCTION + temperature 0.1.

Risk score heuristic (deterministic, no LLM):
  - +0.3 if touches >5 files
  - +0.2 if touches a hub module (from graph store)
  - +0.2 if touches a config file
  - +0.1 per 100 net lines changed (capped at 0.4)
  - 0.0 baseline
  Capped at 1.0.
"""

from src.rag.grounding import prepend_grounding, contains_abstain, ABSTAIN_TOKEN

ALLOWED_INTENTS = {"feature", "fix", "refactor", "chore", "docs", "test", "unknown"}

def enrich_commit(
    commit: Commit,
    files: list[FileChange],
    diff_text: str,
    *,
    llm_client,
    config: dict,
    graph_store=None,   # for hub-module detection
) -> dict:
    ...

def enrich_pending(store: TemporalStore, *, llm_client, config: dict) -> int:
    """Enrich all unenriched commits in the store. Returns count enriched."""
    ...
```

The prompt for enrichment:
```
You are summarizing a single git commit.

Files changed:
<file list>

Commit message:
<subject + body>

Diff (may be truncated):
<diff>

Produce STRICT JSON:
{
  "intent": "feature|fix|refactor|chore|docs|test|unknown",
  "summary": "1-2 sentence narrative, max 200 chars",
  "modules_affected": ["..."]   // each MUST appear as a path prefix in the files list
}

Rules:
- Use ONLY module names that appear in the files list.
- Do NOT invent class names, design intentions, or features.
- If the commit's purpose is unclear from the inputs, return intent=unknown and summary=[INSUFFICIENT_EVIDENCE].
```

The post-processing strips and validates JSON; on parse failure, retry once with stricter prompt; on second failure, store as `intent: unknown, summary: [INSUFFICIENT_EVIDENCE]`.

**ACCEPTANCE**
- Run on the last 50 commits of the agent-hub repo itself. Sample 20:
  - ≥80% have a coherent summary.
  - 0 hallucinated module names.
  - Intent classification is sensible (judge subjectively but record disagreements).
- `enrich_pending` is incremental: re-running doesn't re-enrich.

**ANTI-PATTERNS**
- Do NOT enrich every commit ever — start from a configurable bootstrap point (default: 100 commits ago).
- Do NOT use `git log --pretty=fuller` and feed everything to LLM. Page commit by commit.

---

### T-305 — Daily/weekly digest renderer `src/temporal/digest.py`

**Mode**: `roadmap-executor`
**Effort**: 1.5 days
**Depends on**: T-303, T-304.

**CONTEXT**
A digest is a rendering of enriched commits over a time window: daily summary, weekly summary, per-module summary. It's not an LLM call — it's pure formatting from the store. (LLM-grouped digests are an advanced feature for Phase 5.)

**FILE**: `src/temporal/digest.py`

```python
"""Render digests from the temporal store.

Output formats: markdown (default), html, json, slack_blocks.

Group commits by intent, then chronologically. Highlight high-risk commits.
"""

from datetime import date, timedelta

def render_daily(store: TemporalStore, day: date, fmt: str = "markdown") -> str: ...
def render_weekly(store: TemporalStore, week_ending: date, fmt: str = "markdown") -> str: ...
def render_module(store: TemporalStore, module: str, days: int = 7, fmt: str = "markdown") -> str: ...
```

Markdown daily example output:
```markdown
# Changelog — 2026-04-18

**12 commits** by 4 authors. **2 high-risk** changes.

## Features (3)
- `feat(auth)`: Add SAML 2.0 SSO support.
  Modules: `src/auth`, `src/web`. Risk: 0.6. → ([abc1234](link))
- ...

## Fixes (5)
- ...

## Refactors (2)
- ...

## Chore (2)
- ...

---
*Generated by Agent Hub temporal digest.*
```

**ACCEPTANCE**
- `render_daily(store, date(2026, 4, 18))` returns a non-empty markdown string when commits exist.
- Empty days return `"# Changelog — YYYY-MM-DD\n\nNo commits."`.
- `slack_blocks` format produces valid Slack Block Kit JSON.

---

### T-306 — Pluggable delivery channels

**Mode**: `roadmap-executor`
**Effort**: 1.5 days
**Depends on**: T-305.

**CONTEXT**
Per DECIDE-8, the user wants flexibility on delivery: markdown file, Slack, email, possibly more. Build a small plugin system.

**FILES**: `src/temporal/channels/__init__.py`, `file.py`, `slack.py`, `email.py`.

```python
# src/temporal/channels/__init__.py
"""Pluggable delivery channels for changelog digests.

Each channel implements:
  class Channel:
      name: str
      def send(self, content: str, *, fmt: str, meta: dict) -> None: ...

Channels are loaded from config:

    temporal:
      delivery:
        - type: file
          path: context/changelog/{date}.md
        - type: slack
          webhook_url_env: SLACK_WEBHOOK_URL
          channel: "#dev-changelog"
        - type: email
          smtp_host_env: SMTP_HOST
          to: ["dev-team@example.com"]
          subject: "Daily changelog — {date}"
"""

CHANNEL_REGISTRY: dict[str, type] = {}

def register(name: str):
    def deco(cls):
        CHANNEL_REGISTRY[name] = cls
        return cls
    return deco

def load_channels(config: dict) -> list:
    return [CHANNEL_REGISTRY[c["type"]](**c) for c in config.get("delivery", [])]
```

**Channel implementations**:

- `file.py`: write to disk; `path` template supports `{date}`, `{week}`.
- `slack.py`: POST to webhook; render via `slack_blocks` format.
- `email.py`: SMTP (use stdlib `smtplib`). Wrap markdown in HTML via `markdown` package (already a likely dep) for richer rendering.

**Secrets handling**: webhook URLs and SMTP creds come from `.env` only (referenced via `*_env` keys), never inline in config.

**ACCEPTANCE**
- `python -m src.temporal.send_digest --day=today` writes to all configured channels.
- Slack webhook can be tested with `--channel=slack --dry-run` (prints the JSON payload).
- Email channel can be tested with `--channel=email --dry-run` (prints the rendered email).
- Missing required env var causes a clear error message, not a crash.

**ANTI-PATTERNS**
- Do NOT add a webhook URL with credentials in `config.yaml` — only env var references.
- Do NOT block scan/synthesis on delivery failure; log and continue.

---

### T-307 — Rewrite `watch.py` to use the new git-aware loop

**Mode**: `roadmap-executor`
**Effort**: 1.5 days
**Depends on**: T-302..T-306.

**CONTEXT**
The current `watch.py` mixes file-system watching for indexing AND for changelog. Split responsibilities:
- Indexing trigger remains file-aware (so non-committed changes still update the RAG).
- Changelog trigger becomes git-aware (only committed work appears in changelog).

Indexer-loop config in `scripts/indexer-loop.sh` chains:
1. `git fetch && git pull` (if `temporal.auto_pull: true`).
2. `python watch.py --reindex` — incremental ingest.
3. `python synthesize.py` — refresh pyramid.
4. `python build_graph.py` — refresh graph.
5. `python -m src.temporal.run_changelog` — enrich new commits, render digest, deliver.

**FILE**: `watch.py` (rewrite the changelog branch only; keep the FS watcher for ingest).

```python
"""Watch loop for Agent Hub.

Two responsibilities:
  1. Detect changed files in workspace → trigger incremental ingest.
  2. Detect new git commits → enrich + digest + deliver.

Modes:
  python watch.py                      # default: both, run once and exit
  python watch.py --reindex-only       # ingest only
  python watch.py --changelog-only     # changelog only
  python watch.py --bootstrap          # baseline both states without acting
  python watch.py --status             # show what would change, do nothing
"""
```

**FILE**: `src/temporal/run_changelog.py`

```python
"""Top-level changelog runner.

1. read state (last_indexed_sha)
2. new_commits_since(sha)
3. for each commit: store.upsert_commit
4. enrich_pending
5. render daily digest for today
6. send via configured channels
7. update state
"""
```

**CONFIG ADDITIONS** (`config.yaml`):
```yaml
temporal:
  enabled: true
  auto_pull: false                   # if true, runs `git pull` before each cycle
  bootstrap_commits: 100             # how far back to start when state is empty
  enrichment:
    model: heavy                     # alias from config.yaml: models
    max_diff_lines: 2000             # truncate big diffs
    abstain_on_failure: true
  digests:
    daily: true                      # generate a daily digest
    weekly: true                     # weekly on Mondays
  delivery:
    - type: file
      path: context/changelog/{date}.md
    # uncomment to enable Slack:
    # - type: slack
    #   webhook_url_env: SLACK_WEBHOOK_URL
    #   channel: "#dev-changelog"
```

**ACCEPTANCE**
- `python watch.py --status` prints number of commits to enrich + files to index.
- A full cycle: makes 3 commits, runs `python watch.py`, observes:
  - 3 entries appear in `context/temporal/store.sqlite`.
  - 3 entries appear in today's markdown digest.
  - If Slack configured, payload sent.
- Re-running `watch.py` doesn't duplicate work.

---

### T-308 — Admin UI: `/admin/changelog`

**Mode**: `roadmap-executor`
**Effort**: 1 day
**Depends on**: T-307.

**CONTEXT**
Browsable changelog view for humans. Read-only.

**FILES**:
- `web/admin_routes.py`: `GET /admin/changelog?days=14` returns rendered HTML.
- `web/admin/changelog.html`: timeline view, filterable by intent / module / risk.

**ACCEPTANCE**
- Page loads in <500ms for 100 days of commits.
- Filtering works.
- Each entry links to its commit (use `git remote get-url origin` to construct the URL; if origin is GitHub/GitLab, link to `/<owner>/<repo>/commit/<sha>`).

---

## 4. Phase 3 success gate

- [ ] Audit document exists with concrete failure modes.
- [ ] Git-aware loop replaces filesystem polling for changelog.
- [ ] Re-running watch on unchanged repo does nothing observable in changelog.
- [ ] Sample of 20 enriched commits: 0 hallucinated modules, ≥80% coherent summaries.
- [ ] Daily digest is generated as markdown automatically; configured Slack channel receives it.
- [ ] `/admin/changelog` displays the timeline.

---

## 5. Files Phase 3 produces / modifies

| File | New / Modified |
|------|----------------|
| `docs/diagnostics/changelog_audit.md` | NEW (T-301) |
| `src/temporal/git_client.py` | NEW |
| `src/temporal/store.py` | NEW |
| `src/temporal/enricher.py` | NEW |
| `src/temporal/digest.py` | NEW |
| `src/temporal/channels/__init__.py` | NEW |
| `src/temporal/channels/file.py` | NEW |
| `src/temporal/channels/slack.py` | NEW |
| `src/temporal/channels/email.py` | NEW |
| `src/temporal/run_changelog.py` | NEW |
| `watch.py` | REWRITTEN (changelog branch) |
| `scripts/indexer-loop.sh` | MODIFIED (add changelog step) |
| `config.yaml` | MODIFIED (temporal section) |
| `.env.example` | MODIFIED (SLACK_WEBHOOK_URL, SMTP_HOST etc.) |
| `web/admin_routes.py` | MODIFIED (add /admin/changelog) |
| `web/admin/changelog.html` | NEW |
| `tests/test_temporal_*.py` | NEW (4 files) |

---

*End of Phase 3. The temporal store from this phase becomes the data source for the temporal MCP tools (`recent_changes`, `explain_change`, `why_does_this_exist`, `blame_plus`, `what_changed_here`) in Phase 4.*
