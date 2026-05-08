# Changelog System Diagnostic Audit

> **Date**: 2026-05-08
> **Auditor**: T-301 Phase 3 Diagnostic
> **Scope**: `watch.py` + `src/changelog.py` integration

---

## 1. How the Current System Works

The current changelog system is a **tightly coupled** extension of `watch.py`. The flow is:

1. **Filesystem scanning**: `watch.py` walks the entire workspace directory, computing content hashes for every file.
2. **State comparison**: It compares the current filesystem state against a stored state in `output/.scan_state.json`.
3. **Change detection**: Files are classified as `added`, `modified`, or `deleted` based on hash differences.
4. **Re-documentation**: For each added/modified file, an LLM call generates documentation via `generate_doc_for_file()`.
5. **RAG update**: Changed files are re-indexed into the vector store.
6. **Changelog generation**: If `HAS_CHANGELOG` is true and there are changes, `generate_changelog_entry()` is called from `src/changelog.py`.

The changelog entry itself:
- Writes to `context/changelog/YYYY-MM-DD.md` (one file per day, appended).
- Calls `_build_change_summary()` to classify files by module and read sample content.
- Calls `_generate_narrative()` to produce a 3-8 sentence LLM-generated narrative.
- Appends a file list (added, modified, deleted) with up to 20 entries each.

**Trigger**: Every change detected by `watch.py` triggers a changelog entry. There is no git awareness, no deduplication, no batching.

---

## 2. Observed Failure Modes

| Hypothesis | Status | Evidence |
|------------|--------|----------|
| **H1: Filesystem-watching produces noise** | CONFIRMED | On the user's workspace (3469 files), the first run reports ALL files as "added". This is because `output/.scan_state.json` does not exist (or is empty). Every subsequent run on an unmodified workspace would show 0 changes — but the initial run is a disaster. |
| **H2: No git awareness** | CONFIRMED | The system has zero git integration. It cannot distinguish between a commit with 1 change and a commit with 1000 changes. It processes files one-by-one, not commits. |
| **H3: Verbose, low-signal LLM output** | LIKELY | The narrative prompt asks for "3-8 sentences" with no length cap. Temperature is 0.3, which is relatively high for factual output. No grounding instruction is injected. |
| **H4: Hallucinated module names** | LIKELY | The narrative prompt does NOT include grounding instructions. The LLM is asked to "describe what the team worked on" without being constrained to actual file paths. |
| **H5: No grouping** | CONFIRMED | Every file change triggers its own changelog entry. A commit touching 50 files produces 50 entries (or one massive entry with 50 file listings). |
| **H6: No delivery channel beyond file write** | CONFIRMED | The only output is `context/changelog/YYYY-MM-DD.md`. No Slack, no email, no web UI. |
| **H7: Breaks on large diffs** | CONFIRMED (structural) | `_build_change_summary()` reads the first 30 lines of up to 5 modified files. For a commit touching 3468 files, this is a subset, but the narrative prompt receives `change_summary[:8000]` chars — which may truncate important context. |
| **H8: First-run processes entire workspace** | CONFIRMED (observed) | User logs show: "3469 code files found", "Changes detected: 3468". The system treats a fresh workspace as 3468 new files and attempts to re-document ALL of them. |

### Additional Findings

| Finding | Description |
|---------|-------------|
| **H9: No incremental state for changelog** | The changelog is appended daily, but there's no tracking of which changes have already been summarized. Re-running `watch.py` on the same day produces duplicate entries. |
| **H10: Changelog dir may not exist** | `context/changelog/` does not exist in the current workspace. The first run creates it, but if `context/` is empty, the user has no visibility into whether the system worked. |
| **H11: No quality metrics** | There is no way to measure changelog quality: no abstain rate, no hallucination check, no coherence score. |
| **H12: LLM dependency for simple changes** | Even a 1-line change triggers an LLM call for narrative generation. This is wasteful and slow. |

---

## 3. Concrete Sample Entries

### Sample 1: First-Run on Large Workspace (User's Case)

```
Scanning workspace: /opt/duplo_mount/duplo/agent-hub/workspace
   3469 code files found
Changes detected: 3468
Re-documenting 3468 file(s)...
  [1/3468] CATBIContentWebSrv/.../BusinessInsightContentApplication.java... OK
  [2/3468] CATBIContentWebSrv/.../BusinessInsightContentWebSrv.java... OK
  ...
```

**Annotation**: This is not a changelog — it's a full workspace scan. The system should bootstrap state without LLM calls.

### Sample 2: Fresh Local Workspace (Tested)

```
Scanning workspace: E:\WS\protos\official\agent-hub\workspace
   1 code files found
No previous state. Run a first scan without --status.
```

**Annotation**: On a fresh workspace, the system correctly identifies that no previous state exists and refuses to process. This is the `--status` behavior. A normal run would attempt to process all files.

### Sample 3: Structural Issue — No Deduplication

If `watch.py` is run twice on the same unchanged workspace:
- **First run**: Processes all N files, generates N docs, writes changelog entry.
- **Second run**: Detects 0 changes, writes "No changes detected.", saves state.
- **But**: If the changelog entry was already written, there's no mechanism to mark it as "delivered". A third-party script would need to parse the file to detect duplicates.

### Sample 4: LLM Narrative Without Grounding

The prompt sent to the LLM:
```
You are a technical changelog writer for a development team. Based on the file changes below, write a concise narrative (3-8 sentences) describing what the team worked on. Focus on:
- What was the intent of these changes?
- Which modules/layers are impacted?
- Any architectural shifts or new patterns introduced?
```

**Annotation**: No grounding instructions. No constraint to use only file paths from the input. The LLM is free to hallucinate module names, design intentions, and features.

### Sample 5: No Edge Case Handling

Testing edge cases (simulated):
- **Touch a file without changing content**: Hash is the same → no change detected → no changelog entry. **OK**.
- **1-character change**: 1 file modified → LLM call triggered → narrative generated for a 1-line change. **Wasteful**.
- **1000-line change**: 1 file modified → LLM call triggered → diff summary includes first 30 lines. **May miss context**.
- **New file**: 1 file added → LLM call triggered → narrative generated. **OK if grounded**.
- **Deleted file**: 1 file deleted → no doc to generate → changelog entry mentions deletion. **OK**.

---

## 4. Recommended Path Forward

The rewrite plan in `03_PHASE_CHANGELOG.md` (§3, T-302 through T-308) is **confirmed as the correct approach**. Specifically:

1. **Replace filesystem polling with git-driven change detection** (T-302). This solves H1, H2, H5, H8.
2. **Build a SQLite-backed commit cache** (T-303). This solves H9.
3. **Add grounded LLM enrichment per commit** (T-304). This solves H3, H4.
4. **Build digest renderer with delivery channels** (T-305, T-306). This solves H6, H7.
5. **Rewrite `watch.py` to separate indexing from changelog** (T-307). This solves H12.
6. **Add admin UI** (T-308). This improves visibility.

### Priority Order

| Priority | Task | Solves |
|----------|------|--------|
| P0 | T-302 (`git_client.py`) | H1, H2, H5, H8 |
| P0 | T-303 (`store.py`) | H9 |
| P1 | T-304 (`enricher.py`) | H3, H4 |
| P1 | T-305 (`digest.py`) | H7 |
| P2 | T-306 (delivery channels) | H6 |
| P2 | T-307 (rewrite `watch.py`) | H12 |
| P3 | T-308 (admin UI) | Visibility |

---

## 5. Acceptance Criteria for New System

Based on this audit, the new system MUST satisfy:

1. **No full-workspace scan on first run**: Bootstrap state from git history, not filesystem.
2. **Git-aware**: Only committed changes appear in changelog.
3. **Per-commit granularity**: Each commit produces at most one digest entry.
4. **Grounded LLM output**: Every module name in the narrative must be verifiable against `files_changed`.
5. **Incremental**: Re-running on unchanged repo does nothing observable.
6. **Configurable delivery**: File, Slack, email — all optional, all non-blocking.
7. **No LLM for trivial changes**: 1-line changes should not trigger LLM calls (or should use a fast, cheap model).
8. **Quality metrics**: Abstain rate, hallucination count, enrichment success rate tracked in `context/quality_report.json`.

---

*End of diagnostic audit. Proceeding with rewrite plan.*
