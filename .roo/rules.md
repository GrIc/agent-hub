# Agent Hub — Roo Rules

> Loaded on every call, every mode. Keep short. Do not violate these rules under any circumstance.

---

## 1. Grounding (existential)

1. Every name (class, method, field, file, module) you write in code comments, docstrings, documentation, or LLM prompts MUST exist in the source you're describing.
2. If you cannot verify a name exists, OMIT it or use `[INSUFFICIENT_EVIDENCE]`.
3. Do NOT invent plausible-sounding framework terms as if they were project entities.
4. Validation of your output happens in CI. Hallucinated names = rejected PR.

## 2. Language

All code, comments, docstrings, log messages, commit messages, and agent definitions are in **English only**. No exceptions. The user may write prompts in French; the output is English.

## 3. Scope discipline

1. Modify ONLY the files listed in the current task's `FILES` section.
2. Create new files ONLY if listed.
3. If the task seems to require modifying files not listed, STOP and ask.
4. Do NOT add tangential improvements ("while I'm here, I'll also refactor X"). Tangents go in a new task.

## 4. When in doubt, ASK

If any of these are true, stop and ask the human before proceeding:
- A required file listed in FILES doesn't exist and isn't marked NEW.
- A dependency between tasks seems inverted.
- A config key referenced in the task doesn't exist in `config.yaml` and isn't being added by the task.
- You'd need a new pip package to complete the task.
- Acceptance criteria seem unachievable with the spec given.

Asking is cheap. Guessing is expensive.

## 5. Complete files

Produce **full file contents**. Do NOT:
- use `...` or `# rest stays the same` or similar.
- produce diffs or patches.
- split a file across "I'll finish next message" without explicit acknowledgment from the human.

If a file is too large for one response, split it at a natural boundary (function, class) and produce each piece as a complete message of its own.

## 6. Mode discipline

1. Check the current task's `Mode:` line.
2. If it doesn't match the Roo mode you're running in, STOP and tell the human to switch modes.
3. Do not execute out of mode.

## 7. Test-before-done

Every task's ACCEPTANCE section is mandatory. Before declaring done:
- Run `pytest tests/` and show the output.
- If the task modifies indexing, synthesis, or MCP: also run the relevant golden test.
- If the task touches Docker: `docker compose up -d && curl localhost:8080/healthz`.

Failing tests block task completion. Do not claim "works on my machine" — run the tests.

## 8. Config over code

New behaviors get config keys in `config.yaml` with:
- documented default,
- type (int / str / bool / list / dict),
- a comment explaining what it controls.

Do not hardcode values that could reasonably change (paths, limits, model names, timeouts, URLs).

## 9. No new dependencies without approval

If a task needs a new pip/npm package:
- name it explicitly,
- justify why stdlib + existing deps won't do,
- stop and await human approval.

## 10. Secrets

Never put credentials, tokens, webhook URLs, or API keys in:
- source code,
- `config.yaml`,
- commit messages,
- log output.

Always via `.env` referenced by `*_env` keys in config.

## 11. Commit hygiene

- Reference task ID: `feat(phase-1): grounding module (T-101)`, `chore(phase-0): remove code agent (T-003)`, etc.
- Conventional commits: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`.
- No `WIP` commits on main — squash before merge.

## 12. Patches / diffs

**Deliverables are complete files, not patches.** The user has tried patch-based workflows with weaker models and they fail. If the task spec says "modify file X", produce X in its entirety.

---

*End of rules. For project context see `.roo/context.md`.*
