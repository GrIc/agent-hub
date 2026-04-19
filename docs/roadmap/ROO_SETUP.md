# ROO_SETUP — where to put what, and how Roo Code loads it

> **Audience**: you (the human), when wiring Roo Code to this roadmap.
> **Target executor**: Roo Code with a model like `nemotron-3-super-120b-a12b` (or whatever you've configured on your vLLM).

---

## 1. File placement summary

```
agent-hub/
├── .roo/                           ← Roo Code config (versioned)
│   ├── rules.md                    ← loaded by ALL modes, every call
│   ├── context.md                  ← loaded by ALL modes, every call
│   └── skills/                     ← loaded selectively by specific modes
│       ├── grounding.md            ← loaded by kip-engineer
│       ├── ast-extraction.md       ← loaded by graph-engineer
│       └── mcp-framework.md        ← loaded by mcp-engineer
├── .roomodes                       ← YAML of custom Roo modes (repo root!)
├── docs/
│   ├── roadmap/                    ← versioned, agent-readable roadmap
│   │   ├── 00_MASTER_ROADMAP.md
│   │   ├── 01_PHASE_GROUNDING.md
│   │   ├── 02_PHASE_GRAPHRAG.md
│   │   ├── 03_PHASE_CHANGELOG.md
│   │   ├── 04_PHASE_MCP_TOOLS.md
│   │   ├── 05_PHASE_ADVANCED.md
│   │   ├── EXTRACT_PROJECTS_REPO.md
│   │   ├── ROO_SETUP.md            ← this file
│   │   └── TASK_TEMPLATE.md
│   └── decisions/                  ← ADRs (one per DECIDE-*)
│       └── 0001-*.md through 0008-*.md
└── scripts/
    └── extract_projects.sh         ← DECIDE-1 extraction
```

### Why not `.claude/`?

Because you're driving this with Roo Code, not Claude Code directly. Roo's mode system (`.roomodes`), rules (`.roo/rules.md`), and skills (`.roo/skills/`) are the right abstraction. If later you also want to use Claude Code for something, you can add a `.claude/` directory alongside — Claude Code and Roo Code respect their own directories and will coexist.

### Why `docs/roadmap/` and not `.roo/roadmap/`?

Because the roadmap is **documentation for humans AND agents**, and belongs in the normal docs tree. Agents read it via file-read tools; humans review it via GitHub/GitLab. Putting it under `.roo/` would hide it from reviewers.

---

## 2. What loads when

Roo Code's behavior (verify against your specific Roo version):

| Artifact | Loaded when | Purpose |
|----------|-------------|---------|
| `.roo/rules.md` | Every message, every mode | Hard rules — never violate these. |
| `.roo/context.md` | Every message, every mode | Project context — stack, conventions, where things live. |
| `.roo/skills/<skill>.md` | When the current mode's `skills:` list includes it | Deeper "how to do X well" guidance for specialized work. |
| `.roomodes` (YAML) | Mode selection | The list of custom modes available. |
| `docs/**/*.md` | When an agent opens the file | On-demand reference — the roadmap, ADRs, etc. |

Keep `rules.md` and `context.md` **short** (≤ 300 lines combined). They're in every context window. Put volume in skills and docs, which are opt-in.

---

## 3. Custom Roo modes to add

We propose **5 custom modes**. Each has a single, narrow job. Weaker models do much better with narrow modes than with a general "do the roadmap" mode.

### Mode 1 — `roadmap-executor` (generic default)

- **Role**: execute any task from the roadmap that doesn't require specialized knowledge.
- **Skills loaded**: none (uses rules + context only).
- **Typical tasks**: cleanup (Phase 0), simple refactors, doc updates, admin-route additions.
- **Trade-off**: fast, cheap, but won't know grounding tricks. Use other modes for anything touching the indexing pipeline.

### Mode 2 — `kip-engineer`

- **Role**: all work on the indexing pipeline where hallucination is a risk.
- **Skills loaded**: `grounding.md`.
- **Typical tasks**: T-101..T-108 (Phase 1), T-301..T-304 (Phase 3 diagnose + enricher).
- **Special instructions**: prompt emphasizes reading source files before writing code, validating every identifier reference, and preferring to abstain over guess.

### Mode 3 — `graph-engineer`

- **Role**: AST + graph work (Phase 2).
- **Skills loaded**: `grounding.md`, `ast-extraction.md`.
- **Typical tasks**: T-201..T-207, plus graph-related MCP tools (T-440..445).
- **Special instructions**: prompt emphasizes that **zero LLM calls** go into structural extraction; LLM is for enrichment only.

### Mode 4 — `mcp-engineer`

- **Role**: MCP server framework and tools.
- **Skills loaded**: `mcp-framework.md`, `grounding.md`.
- **Typical tasks**: T-401..T-460 (Phase 4), Phase 5 tool tasks.
- **Special instructions**: every new tool MUST inherit `BaseTool`, declare schemas, set `requires_citations` appropriately, and ship a golden test.

### Mode 5 — `deprecator`

- **Role**: clean removal of code.
- **Skills loaded**: none.
- **Typical tasks**: T-001, T-002, T-003 (Phase 0).
- **Special instructions**: prompt emphasizes removing all references, not leaving commented-out code, updating docs/configs, and running tests after removal. Explicitly bans introducing "backward compat" shims.

### (Optional) Mode 6 — `changelog-doctor`

- **Role**: T-301 diagnostic only.
- **Skills loaded**: none.
- **Typical tasks**: T-301.
- **Special instructions**: prompt emphasizes observation before rewrite, no code changes, only `docs/diagnostics/changelog_audit.md` writes.

---

## 4. Mode switching strategy

Each task in the roadmap includes a `Mode:` line stating which mode should execute it. If an agent is asked to do the task under the wrong mode, it should refuse and request a switch. The relevant snippet in `.roo/rules.md`:

> **Mode discipline**: if the current task's `Mode:` line doesn't match your current Roo mode, say so and stop. Do not execute out of mode.

This forces the human (you) to explicitly switch modes before each new task, which in practice is a good signal that a logical unit is ending.

---

## 5. Minimal workflow per task

```
1. You read the phase document, pick task T-XXX.
2. You switch Roo mode to the one specified.
3. You paste this prompt into Roo:
     "Execute task T-XXX from docs/roadmap/0Y_PHASE_*.md.
      Confirm you've read the task, the relevant rules/context/skills.
      List the files you'll create/modify. Then proceed."
4. Agent: reads roadmap, lists files, produces code.
5. You: review, run tests, commit.
6. (Mark T-XXX as done in master roadmap or tracking system.)
```

---

## 6. Model tuning recommendations

For Nemotron-class models (or similar 70-120B):

| Setting | Value | Why |
|---------|-------|-----|
| Temperature | 0.2 | Determinism for code. |
| Top-p | 0.9 | Allow some variety for naming. |
| Max tokens per response | 8000 | Enough for a full file; prevents runaway. |
| System prompt | minimal | Put intelligence in `.roo/` files, not in system prompt. |
| Tool use | ON (read/write files, run shell) | Roo uses these directly. |
| Memory / long-term storage | OFF | Roadmap is the memory. |

For smaller models (< 70B) you may need to:
- Shorten `.roo/rules.md` even more.
- Execute one file at a time.
- Use the `deprecator` mode for anything destructive (it has the simplest ruleset).

---

## 7. Validation workflow

After each task, before marking done:

1. **Automated**:
   - `pytest tests/` — must pass.
   - `docker compose up -d && curl localhost:8080/healthz` — must return 200.
   - Phase 1+: golden test `tests/golden/test_no_hallucinations.py` — must pass.
2. **Manual spot-check**:
   - Read the diff. Does it match the task?
   - Are there any hallucinated names in comments or docstrings?
   - Does the agent's commit message match the task ID (T-XXX)?
3. **Commit format**:
   - Conventional commits: `feat(phase-1): implement grounding module (T-101)`, `chore(phase-0): extract projects pipeline (T-001)`, etc.

---

## 8. Troubleshooting

**Agent ignores rules.md**. Shorten `.roo/rules.md` to ≤ 100 lines and make the most important rule #1. If a rule is regularly violated, restructure to make it harder to miss.

**Agent invents files not in the roadmap**. Add to rules.md: "Create ONLY the files listed in the task's FILES section. New files require explicit approval."

**Agent produces partial code**. Add to rules.md: "Produce complete files. Never use ellipses (`...`), never use 'I'll finish later'. If a task is too big for one response, split your work across multiple messages, each producing one or more complete files."

**Agent gets mode discipline wrong**. Make your prompt explicitly include the task header including the `Mode:` line. Some models ignore repo context when prompt is short.

---

*Now set up `.roo/rules.md`, `.roo/context.md`, and `.roomodes`.*
