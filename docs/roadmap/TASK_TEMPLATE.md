# TASK_TEMPLATE — how tasks in this roadmap are structured

> Every `T-XXX` task in the phase documents follows this template. If a task you're asked to execute is missing a section, STOP and flag it — a skipped section is usually a bug, not a shortcut.

---

## The template

```
### T-XXX — <Short task title>

Decision:    <DECIDE-n if any, else omit>
Mode:        <roadmap-executor | kip-engineer | graph-engineer | mcp-engineer | deprecator | changelog-doctor>
Effort:      <hours or days>
Depends on:  <list of other T-XXX that must be done first; 'nothing' if standalone>

CONTEXT
2-6 sentences explaining WHY this task exists. Enough that an agent without
the rest of the roadmap loaded would understand the purpose.

FILES (new / modified)
- path/to/new/file.py     (NEW)
- path/to/existing.py     (MODIFIED)
- config.yaml             (MODIFIED)
- ...

CHANGES
A mix of high-level spec and low-level detail. Typical content:
- Functions/classes to add, with signatures and docstrings as the spec.
- Config keys to add, with types and defaults.
- Test cases the new code must satisfy.
- For modifications: the specific sections to touch.

ACCEPTANCE
A checklist, each item verifiable:
- Some command returns/produces X.
- A test passes.
- A metric meets a threshold.
- A file contains Y.

ANTI-PATTERNS
3-6 bullets of "do NOT do X because Y". These are higher-signal than
acceptance criteria for weaker models — they prevent specific common mistakes.
```

---

## Example (well-formed)

```
### T-101 — Create src/rag/grounding.py

Mode:    kip-engineer
Effort:  0.5 day
Depends on: nothing

CONTEXT
A single source of truth for grounding rules. Every LLM call in the indexing
pipeline imports from this module so GROUNDING_INSTRUCTION can evolve in one
place without cross-module drift.

FILES
- src/rag/grounding.py       (NEW)
- tests/test_grounding.py    (NEW)

CHANGES
Create src/rag/grounding.py with:
- G_VERSION = "1.0.0"
- ABSTAIN_TOKEN = "[INSUFFICIENT_EVIDENCE]"
- GROUNDING_INSTRUCTION: a multi-line string (see exact text in 01_PHASE_GROUNDING.md T-101)
- prepend_grounding(system: str) -> str
- contains_abstain(text: str) -> bool
- strip_abstain_blocks(text: str) -> str
- load_noise_filter(config: dict) -> frozenset[str]

Tests in tests/test_grounding.py cover each function.

ACCEPTANCE
- `python -c "from src.rag.grounding import ABSTAIN_TOKEN; print(ABSTAIN_TOKEN)"` prints the token.
- `pytest tests/test_grounding.py` passes.
- `G_VERSION` appears in at least one log call (grep confirms).

ANTI-PATTERNS
- Do NOT add LLM calls in this module — it is pure Python.
- Do NOT change GROUNDING_INSTRUCTION without bumping G_VERSION.
- Do NOT make the module long — if it grows past ~300 lines, split it.
```

---

## Why this shape

| Section | Weak-model failure mode it prevents |
|---------|-------------------------------------|
| `CONTEXT` | "I don't know why I'm doing this" → over/under-engineering. |
| `FILES` | "I'll just modify whatever I feel like" → scope creep. |
| `CHANGES` | "I'll guess the API" → wrong signatures. |
| `ACCEPTANCE` | "I'm done, I promise" → incomplete work. |
| `ANTI-PATTERNS` | "I'll add a helpful little extra thing" → doing the wrong thing harder. |

---

## Agent checklist per task

Before marking a task complete:

1. [ ] Read this task in full.
2. [ ] Read `.roo/rules.md` and `.roo/context.md`.
3. [ ] Read the FILES I'll modify, if they already exist.
4. [ ] Confirm the Mode matches the one the agent is in.
5. [ ] Produce complete file contents (no ellipses, no "implement similarly").
6. [ ] Run the ACCEPTANCE checks. Any failure blocks completion.
7. [ ] Commit with message referencing T-XXX.
8. [ ] Mark task done in the phase document (optional if you use an external tracker).

---

*End of template.*
