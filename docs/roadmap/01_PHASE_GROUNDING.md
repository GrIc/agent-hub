# Phase 1 — Anti-Hallucination Hardening (CRITICAL)

> **This phase is existential.** If MCP tools return hallucinated names, the project is dead. Every other phase depends on this one shipping at quality.
> **Mode**: `kip-engineer` (see `.roomodes`).
> **Effort**: 3 weeks.
> **Prerequisite**: Phase 0 complete.

---

## 1. Re-evaluation of the original KIP_ROADMAP

The original `KIP_ROADMAP.md` is a good starting point but has **9 weaknesses** that must be fixed before we ship MCP tools to external agents. This phase incorporates KIP's good ideas AND fixes the gaps below.

| # | KIP weakness | Why it matters for MCP | Fix in this phase |
|---|-------------|------------------------|-------------------|
| W1 | "Strip hallucinated lines" in synthesis is too lenient | An MCP tool consumed by Cline/Roo cannot ship partially correct prose — the consumer agent will use whatever it gets and amplify the error | Replace with **REJECT-and-abstain**: if validation fails, the doc is regenerated; after 3 failures, the section is replaced by `[INSUFFICIENT_EVIDENCE]` and the file is flagged in the coverage report. |
| W2 | Identifier extraction by regex only is fragile | Regex misses generics, nested classes, lambdas, decorators, annotations | Add **tree-sitter AST extraction** for Java + Python (per DECIDE-5 we invest in structural accuracy). Regex remains as fallback for unsupported languages. |
| W3 | No source attribution at SERVE time | Indexing might be clean but synthesis can still drift; we need a runtime check before sending tool responses | Add a **CitationValidator** middleware in the MCP layer: every tool response is scanned, every code identifier verified against the index. Failures rewrite the response or fail closed. |
| W4 | Noise filter is brittle (hardcoded ~150 framework terms) | New languages or domains break it silently | Make it **config-driven** (`config.yaml: noise_filter.terms`) and **auto-augmentable** from observed imports in the codebase. Provide presets per language/framework. |
| W5 | Validation only checks backtick-quoted names | Hallucinations also live in prose: "the AuthenticationService class handles..." | Validate **any token matching identifier patterns** (CamelCase ≥ 4 chars, snake_case ≥ 4 chars, dotted paths). Backticks are a signal but not the boundary. |
| W6 | Temperature 0.1 is set but no token cap | Long generations correlate with hallucination | Cap output tokens per stage in `config.yaml`. Default: codex per-file 1500, synthesis L2 800, L1 600, L0 400. |
| W7 | No clean abstain mechanism | Models guess instead of admitting ignorance | Every prompt explicitly instructs: "If you cannot ground a claim, write `[INSUFFICIENT_EVIDENCE]` and continue. Do not invent." Validators check for this token's correct usage. |
| W8 | Synthesis pyramid still compounds errors L3→L2→L1→L0 | Even grounded levels can drift across hops | Add **traceability links**: every L1 sentence carries a `→[L2_module]` reference; every L2 paragraph carries `→[L3_file]` references. The CitationValidator can verify the chain. |
| W9 | No coverage / quality dashboard | Nothing tells the team how good the index actually is | Generate `context/quality_report.json` after each scan: per-file validation rate, hallucination examples, abstain rate, retry counts. Display at `/admin/quality` (admin dashboard). |

These nine fixes are baked into the tasks below.

---

## 2. Phase 1 deliverables (overview)

| ID | Deliverable | Lines (est.) |
|----|-------------|--------------|
| `src/rag/grounding.py` | Shared constants, validators, abstain handling | ~250 |
| `src/rag/identifiers.py` | Tree-sitter AST + regex hybrid extractor | ~400 |
| `src/rag/citation_validator.py` | Serve-time validation middleware | ~200 |
| `src/rag/quality_report.py` | Coverage + quality metrics generator | ~150 |
| Updated `src/agents/codex.py` | Strict generation with reject-retry-abstain | (modify) |
| Updated `synthesize.py` | Grounded synthesis with traceability links | (modify) |
| Updated `src/rag/ingest.py` | Rich metadata + line ranges + content hashing | (modify) |
| Updated `agents/defs/codex.md` | Anti-hallucination system prompt | (modify) |
| Updated `config.yaml` | `grounding.*`, `noise_filter.*`, `quality.*` sections | (modify) |
| New `tests/golden/` | Hallucination golden tests (see T-107) | ~500 |
| New `.roo/skills/grounding.md` | Skill loaded by `kip-engineer` mode | ~150 |

---

## 3. Tasks

### T-101 — Create `src/rag/grounding.py`

**Mode**: `kip-engineer`
**Effort**: 0.5 day
**Depends on**: nothing (start here).

**CONTEXT**
A single source of truth for grounding rules. Imported everywhere LLM calls happen.

**FILES**

Create `src/rag/grounding.py` with the following structure (use this as the spec, not as final code — the agent must implement, document, and test it):

```python
"""Shared grounding utilities for all LLM calls in Agent Hub.

Every LLM call in the indexing pipeline (codex, synthesis) and at serve time
(MCP tools that produce prose) MUST go through one of:
- prepend_grounding(system_prompt) for prompt augmentation
- contains_abstain(text) to detect honest abstain
- ABSTAIN_TOKEN as the canonical abstain marker

Do NOT modify GROUNDING_INSTRUCTION without versioning it (G_VERSION).
"""

G_VERSION = "1.0.0"

ABSTAIN_TOKEN = "[INSUFFICIENT_EVIDENCE]"

GROUNDING_INSTRUCTION = """
ABSOLUTE RULES — VIOLATION = REJECT:

1. Mention ONLY names (classes, methods, fields, files, modules) that appear verbatim in the inputs below.
2. If a name does not appear in the inputs, DO NOT mention it. Do NOT invent. Do NOT guess.
3. For every claim about behavior, the supporting code MUST be quotable from the inputs.
4. If you cannot ground a claim, write the literal token [INSUFFICIENT_EVIDENCE] and continue.
   Do NOT fill gaps with plausible-sounding text.
5. When in doubt about whether something exists, omit it.
6. Do NOT use generic framework terms (Spring, JPA, Repository, etc.) as if they were specific
   project entities unless they appear in the inputs as such.

REJECTION POLICY: any output containing names not present in the inputs (other than the
allowed noise-filter terms) will be rejected and you will be asked to retry. Three
rejections will cause this section to be marked as [INSUFFICIENT_EVIDENCE] permanently.
""".strip()


def prepend_grounding(system_prompt: str) -> str:
    """Return system_prompt with GROUNDING_INSTRUCTION prepended.

    Always use this when constructing the system message for an LLM call
    in the indexing pipeline.
    """
    return f"{GROUNDING_INSTRUCTION}\n\n---\n\n{system_prompt}"


def contains_abstain(text: str) -> bool:
    """True if the text contains the canonical abstain token."""
    return ABSTAIN_TOKEN in text


def strip_abstain_blocks(text: str) -> str:
    """Remove [INSUFFICIENT_EVIDENCE] markers cleanly from prose for display.

    Useful at serve time when we want to surface a doc to a human but not
    flood it with abstain markers. The MCP tool layer does NOT use this —
    it preserves the markers as a quality signal.
    """
    # implementation: replace lines containing only the token; replace
    # inline tokens with "(unknown)".
    ...


# === noise filter ===

# Loaded from config.yaml at import time; see load_noise_filter().
DEFAULT_NOISE_FILTER: frozenset[str] = frozenset({
    # generic framework terms — extend in config.yaml: noise_filter.terms
    "Spring", "JPA", "Hibernate", "Repository", "Controller", "Service",
    "Entity", "Component", "Autowired", "Bean", "REST", "HTTP", "JSON",
    "XML", "SQL", "CRUD", "API", "DTO", "DAO", "POJO", "Bean", "ORM",
    # ... (see config.yaml for the full list, this is a fallback only)
})


def load_noise_filter(config: dict) -> frozenset[str]:
    """Build the noise filter from DEFAULT_NOISE_FILTER + config + auto-derived terms.

    config["noise_filter"]["terms"] is a user-extensible list.
    config["noise_filter"]["language_presets"] is a list like ["java-spring", "python-django"].
    Auto-derived: top-N most common imports across the workspace (computed elsewhere).
    """
    ...
```

**ACCEPTANCE**
- File exists at `src/rag/grounding.py`.
- `from src.rag.grounding import GROUNDING_INSTRUCTION, ABSTAIN_TOKEN, prepend_grounding, contains_abstain, load_noise_filter` works.
- Unit tests in `tests/test_grounding.py` cover: prepend, abstain detection, noise filter loading.
- `G_VERSION` is documented and used in log lines so we can track which version produced which doc.

**ANTI-PATTERNS**
- Do NOT make this file long. It is a contract; complexity goes in the consumers.
- Do NOT add LLM calls here. This module is sync-pure.
- Do NOT silently change `GROUNDING_INSTRUCTION` without bumping `G_VERSION`.

---

### T-102 — Create `src/rag/identifiers.py` (AST + regex hybrid extractor)

**Mode**: `kip-engineer` (also tagged `graph-engineer` since GraphRAG depends on this in Phase 2)
**Effort**: 3 days
**Depends on**: T-101.

**CONTEXT**
The original KIP rejected tree-sitter for "simplicity". DECIDE-5 (invest in GraphRAG) overrides that. We now need accurate identifier extraction for both grounding validation AND graph triplet building. Tree-sitter parsers are language-specific WASM files, ~MB each, no native deps.

**SCOPE OF SUPPORT (Phase 1)**:
- Java (primary, given user's codebase)
- Python (we use it ourselves; required for self-tests)
- Fallback: regex-only for any other language.

Phase 2 may add: TypeScript, JavaScript, Go, C++. Out of scope for Phase 1.

**FILES**

Create `src/rag/identifiers.py`:

```python
"""Identifier extraction from source code.

Hybrid strategy:
- For supported languages (Java, Python): tree-sitter AST → highly accurate.
- For unsupported languages: regex fallback → ~80% recall, no false negatives
  on well-formed code, but misses generics / nested classes.

The extracted set is used for:
- Validating LLM-generated docs (Phase 1).
- Seeding graph nodes (Phase 2).

API:
    extract_identifiers(source: str, language: str) -> set[str]
    detect_language(file_path: str) -> str   # by extension
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

# Lazy import; tree-sitter language packages installed via requirements.
try:
    import tree_sitter_java
    import tree_sitter_python
    from tree_sitter import Language, Parser
    _TS_AVAILABLE = True
except ImportError:
    _TS_AVAILABLE = False


_EXT_TO_LANG = {
    ".java": "java",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".h": "cpp", ".hpp": "cpp",
}


def detect_language(file_path: str) -> str:
    return _EXT_TO_LANG.get(Path(file_path).suffix.lower(), "unknown")


# ---- regex fallback ----

_RE_CLASS = re.compile(r"\b(?:class|interface|enum|record|trait|struct)\s+([A-Z][A-Za-z0-9_]+)")
_RE_PY_DEF = re.compile(r"\bdef\s+([a-z_][a-zA-Z0-9_]+)\s*\(")
_RE_JAVA_METHOD = re.compile(r"\b(?:public|protected|private|static|final|abstract|synchronized|\s)+\w[\w<>,\s]*\s+([a-z_][A-Za-z0-9_]+)\s*\(")
_RE_CAMELCASE = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b")  # ≥ 2 humps

def _extract_regex(source: str) -> set[str]:
    ids = set()
    ids.update(m.group(1) for m in _RE_CLASS.finditer(source))
    ids.update(m.group(1) for m in _RE_PY_DEF.finditer(source))
    ids.update(m.group(1) for m in _RE_JAVA_METHOD.finditer(source))
    ids.update(m.group(1) for m in _RE_CAMELCASE.finditer(source))
    return {i for i in ids if len(i) >= 4}


# ---- AST (tree-sitter) ----

_PARSER_CACHE: dict[str, "Parser"] = {}

def _get_parser(language: str) -> "Parser | None":
    if not _TS_AVAILABLE:
        return None
    if language in _PARSER_CACHE:
        return _PARSER_CACHE[language]
    try:
        if language == "java":
            lang = Language(tree_sitter_java.language())
        elif language == "python":
            lang = Language(tree_sitter_python.language())
        else:
            return None
        parser = Parser(lang)
        _PARSER_CACHE[language] = parser
        return parser
    except Exception:
        return None


# Per-language node-type → identifier-extraction strategy.
# Walk the AST, collect names from declaration nodes only.
_JAVA_DECL_TYPES = {
    "class_declaration", "interface_declaration", "enum_declaration",
    "method_declaration", "field_declaration", "constructor_declaration",
    "annotation_type_declaration", "record_declaration",
}
_PYTHON_DECL_TYPES = {
    "class_definition", "function_definition", "assignment",
}


def _extract_ast_java(source: str) -> set[str]:
    parser = _get_parser("java")
    if parser is None:
        return _extract_regex(source)
    tree = parser.parse(source.encode("utf-8"))
    out = set()
    cursor = tree.walk()

    def walk(node):
        if node.type in _JAVA_DECL_TYPES:
            # find the 'name' child if present
            name_node = node.child_by_field_name("name")
            if name_node:
                out.add(name_node.text.decode("utf-8"))
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return {i for i in out if len(i) >= 2}


def _extract_ast_python(source: str) -> set[str]:
    # similar; left as exercise — see Java for the pattern
    ...


# ---- public API ----

def extract_identifiers(source: str, language: str | None = None) -> set[str]:
    """Extract identifiers (class names, method names, top-level fields) from source code.

    Returns a set of strings. Empty if extraction fails.
    """
    if language is None:
        return _extract_regex(source)
    if language == "java":
        return _extract_ast_java(source)
    if language == "python":
        return _extract_ast_python(source)
    return _extract_regex(source)
```

Add to `requirements.txt`:
```
tree-sitter>=0.22
tree-sitter-java>=0.23
tree-sitter-python>=0.23
```

**ACCEPTANCE**
- Unit tests in `tests/test_identifiers.py` cover:
  - 5 hand-crafted Java files (nested classes, generics, lombok-like annotations).
  - 5 hand-crafted Python files (dataclasses, decorators, async).
  - 1 unsupported language (e.g. Rust) → falls back to regex without crash.
- On a real Java file from the workspace (pick an existing file if present, e.g. `src/main/java/com/example`), extraction returns ≥95% of class/method names that `javap` or `jdt` would report.
- Extraction of a 1MB Java file completes in <500ms.
- `tree-sitter` import failure → graceful fallback to regex with a single WARNING log on first call.

**ANTI-PATTERNS**
- Do NOT depend on a JVM-based parser (we're in Python, no Java runtime in the indexer image).
- Do NOT extract every token — only declaration nodes. Else the false-positive rate destroys validation.
- Do NOT cache extraction results in this module — caching belongs to the codex pipeline.

---

### T-103 — Harden `src/agents/codex.py` (reject-retry-abstain)

**Mode**: `kip-engineer`
**Effort**: 2 days
**Depends on**: T-101, T-102.

**CONTEXT**
This is the original KIP §2 task, hardened. Codex generates per-file docs (L3). It must:
- Inject `GROUNDING_INSTRUCTION` into every LLM call.
- Extract identifiers via `extract_identifiers()` before generation.
- Validate generated doc against `known_ids ∪ noise_filter`.
- Retry up to 3 times with progressively stricter prompts.
- After 3 failures, emit `[INSUFFICIENT_EVIDENCE]` for the offending section and log the file in the quality report.

**FILES TO MODIFY**

`src/agents/codex.py`:

Add at the top:
```python
from src.rag.grounding import (
    GROUNDING_INSTRUCTION, ABSTAIN_TOKEN, prepend_grounding,
    contains_abstain, load_noise_filter,
)
from src.rag.identifiers import extract_identifiers, detect_language
from src.rag.quality_report import record_file_quality  # see T-107
```

Add new methods (full implementation expected, this is the spec):

```python
def _validate_doc(
    self,
    doc_text: str,
    known_ids: set[str],
    noise: frozenset[str],
) -> list[str]:
    """Return list of names mentioned in doc_text that are not in known_ids ∪ noise.

    Scans:
      - backtick-quoted tokens
      - CamelCase tokens >= 4 chars
      - snake_case tokens >= 4 chars
      - dotted paths (e.g. com.example.Foo or my.module.bar)

    Excludes: tokens that match common English words via a small built-in stopword
    list (don't reinvent NLTK; ~50 words is enough for this scope).
    """
    ...


def _generate_doc_for_file_strict(
    self,
    file_path: str,
    source_code: str,
    max_retries: int = 3,
) -> tuple[str, dict]:
    """Generate a doc with grounding + reject-retry. Returns (doc, quality_meta).

    quality_meta = {
        "attempts": int,
        "abstained": bool,
        "hallucinated_names_last_attempt": list[str],
        "validation_passed": bool,
        "g_version": str,
    }
    """
    language = detect_language(file_path)
    known_ids = extract_identifiers(source_code, language)
    noise = load_noise_filter(self.config)

    last_doc = ""
    last_hallucinated: list[str] = []
    for attempt in range(max_retries):
        # progressively stricter prompts on retry
        extra = ""
        if attempt > 0 and last_hallucinated:
            extra = (
                f"\n\nIMPORTANT: your previous attempt mentioned these names "
                f"that do NOT exist in the source: {last_hallucinated}. "
                f"Remove them and any sentence that references them. "
                f"If you cannot describe the file without using these names, "
                f"write {ABSTAIN_TOKEN} and stop."
            )
        system = prepend_grounding(self._build_codex_system_prompt() + extra)
        # temperature pinned low for retries
        temp = 0.1 if attempt == 0 else 0.0
        # token cap from config
        max_tokens = self.config["grounding"]["codex_max_tokens"]
        doc = self._llm_call(system=system, user=source_code, temperature=temp, max_tokens=max_tokens)
        last_doc = doc

        if contains_abstain(doc):
            return doc, {
                "attempts": attempt + 1,
                "abstained": True,
                "hallucinated_names_last_attempt": [],
                "validation_passed": True,
                "g_version": self.G_VERSION,
            }

        hallucinated = self._validate_doc(doc, known_ids, noise)
        if not hallucinated:
            return doc, {
                "attempts": attempt + 1,
                "abstained": False,
                "hallucinated_names_last_attempt": [],
                "validation_passed": True,
                "g_version": self.G_VERSION,
            }
        last_hallucinated = hallucinated

    # all retries exhausted: emit abstain doc
    abstain_doc = (
        f"# {Path(file_path).name}\n\n"
        f"{ABSTAIN_TOKEN}\n\n"
        f"Codex could not produce a grounded description for this file after "
        f"{max_retries} attempts. Hallucinated names in last attempt: "
        f"{last_hallucinated[:10]}. The file is excluded from the synthesis pyramid "
        f"and tagged in quality_report.json."
    )
    return abstain_doc, {
        "attempts": max_retries,
        "abstained": True,
        "hallucinated_names_last_attempt": last_hallucinated,
        "validation_passed": False,
        "g_version": self.G_VERSION,
    }
```

In the existing `_scan()` loop, replace direct calls to `_generate_doc_for_file()` with `_generate_doc_for_file_strict()` and call `record_file_quality(file_path, quality_meta)` after each.

**CONFIG ADDITIONS** (`config.yaml`):
```yaml
grounding:
  codex_max_tokens: 1500
  codex_max_retries: 3
  codex_temperature_first_attempt: 0.1
  codex_temperature_retry: 0.0

noise_filter:
  language_presets:
    - java-spring
    - python-stdlib
  terms:
    # user-extensible
    - "MyDomainTerm"
```

**ACCEPTANCE**
- Run `/scan` on a fixture of 20 Java files with hand-checked answers.
- Hallucinated names in produced docs: ≤ 2% (target: 0%).
- Retry rate: ≤ 30% of files require ≥ 1 retry.
- Abstain rate: ≤ 5% of files end up as `[INSUFFICIENT_EVIDENCE]`.
- `context/quality_report.json` contains one entry per file.

**ANTI-PATTERNS**
- Do NOT lower the validation strictness "to keep more docs". A confident wrong answer is worse than abstain.
- Do NOT skip the noise filter — without it, the false-positive rate will look like 50% and you'll be tempted to disable validation.
- Do NOT cache LLM calls on retries — the prompt changes each time.

---

### T-104 — Update `agents/defs/codex.md`

**Mode**: `kip-engineer`
**Effort**: 0.5 day
**Depends on**: T-101.

**CONTEXT**
The agent definition is the system prompt. It must reinforce the grounding contract.

**FILE TO MODIFY**: `agents/defs/codex.md`

Add a new section at the top of the `## Role` block:

```markdown
## Anti-Hallucination Contract

You are a CODE DOCUMENTER, not a code interpreter. Your single rule:

> Mention only what is in the source. If you are unsure, write [INSUFFICIENT_EVIDENCE].

For every file you document:
1. Read the source. Identify visible classes, methods, fields, imports.
2. Describe ONLY those entities, using their exact names.
3. If the file's purpose is unclear from the code alone, write [INSUFFICIENT_EVIDENCE]
   and a short note about what would clarify it (e.g. "missing context: callers,
   parent module purpose").
4. Do NOT use generic framework terms (Spring, JPA, Repository, Controller…)
   as if they refer to specific entities in this project unless they appear in
   the source verbatim.
5. Do NOT speculate about behavior not visible in the code.
6. Cite line numbers when possible: `class X (line 42)`, `method foo (line 117)`.

Validation runs after every generation. Producing names that don't exist in the
source will cause the doc to be rejected and regenerated with stricter constraints.
After 3 rejections the file is permanently flagged.
```

**ACCEPTANCE**
- Manually review the agent def: it includes the Anti-Hallucination Contract.
- A test scan after this change shows the LLM emits `[INSUFFICIENT_EVIDENCE]` at least once on the fixture (proves the abstain mechanism is reachable).

---

### T-105 — Harden `synthesize.py` with grounding + traceability + reject-abstain

**Mode**: `kip-engineer`
**Effort**: 3 days
**Depends on**: T-101, T-102, T-103.

**CONTEXT**
Synthesis builds the pyramid L3 → L2 → L1 → L0. Original KIP just stripped hallucinated lines. We now:
- Inject grounding into all four prompts (`WEIGHTED_DEEPEST_PROMPT`, `WEIGHTED_PARENT_PROMPT`, `L1_PROMPT`, `L0_PROMPT`).
- Validate the output. On failure: regenerate (1 retry) then abstain.
- Add **traceability links**: each L1 sentence ends with `→[L2_module_x]` references; each L2 paragraph ends with `→[L3_file_y, L3_file_z]`. The validator checks these references exist.

**FILES TO MODIFY**

`synthesize.py`:

Replace the `_llm_call` wrapper:

```python
from src.rag.grounding import GROUNDING_INSTRUCTION, ABSTAIN_TOKEN, prepend_grounding, contains_abstain
from src.rag.identifiers import extract_identifiers
from src.rag.quality_report import record_synthesis_quality

def _llm_call_grounded(
    self,
    system: str,
    user: str,
    *,
    input_text_for_validation: str,
    level: str,
    section_id: str,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    retry: bool = True,
) -> str:
    """LLM call with grounding + validation. Returns grounded text or [INSUFFICIENT_EVIDENCE]."""

    grounded_system = prepend_grounding(system)
    if max_tokens is None:
        max_tokens = self.config["grounding"][f"synthesis_{level}_max_tokens"]

    out = self._llm_call(system=grounded_system, user=user, temperature=temperature, max_tokens=max_tokens)
    if contains_abstain(out):
        record_synthesis_quality(level, section_id, abstained=True)
        return out

    cleaned, removed = self._validate_synthesis_output(out, input_text_for_validation)
    if not removed:
        record_synthesis_quality(level, section_id, abstained=False, removed_count=0)
        return cleaned

    if not retry:
        record_synthesis_quality(level, section_id, abstained=False, removed_count=len(removed))
        return cleaned

    # one retry with stricter prompt
    retry_system = prepend_grounding(
        system + f"\n\nPrevious attempt referenced these unknown names: {removed[:10]}. "
        f"Do not use them or any name not present in the inputs."
    )
    out = self._llm_call(system=retry_system, user=user, temperature=0.0, max_tokens=max_tokens)
    if contains_abstain(out):
        record_synthesis_quality(level, section_id, abstained=True)
        return out

    cleaned2, removed2 = self._validate_synthesis_output(out, input_text_for_validation)
    record_synthesis_quality(level, section_id, abstained=False, removed_count=len(removed2))
    if removed2 and len(removed2) > 5:
        return f"{ABSTAIN_TOKEN}\n\nSynthesis at level {level} for {section_id} could not be grounded."
    return cleaned2


def _validate_synthesis_output(
    self,
    output: str,
    input_text: str,
) -> tuple[str, list[str]]:
    """Return (cleaned_output, removed_names).

    A name is removed if it does not appear in input_text AND is not in the noise filter.
    Removed names cause the entire SENTENCE containing them to be dropped.
    """
    # implementation:
    # - extract candidate names from output (CamelCase, snake_case, dotted, backticked)
    # - lowercase compare against input_text and noise filter
    # - drop sentences containing any unknown name
    # - return cleaned text + list of removed names
    ...
```

Replace every `self._llm_call(...)` in synthesis logic with `self._llm_call_grounded(...)`, passing the appropriate `input_text_for_validation` (the concatenation of input docs for that synthesis call) and `level` ("L0", "L1", "L2", or "L3-aggregate").

**Traceability links**: append to every L1/L2 prompt:
> "End every paragraph with a list of source references in the form `→[L3:filename.md]` or `→[L2:module_name]`. Only include references that you actually used."

The validator parses these and checks each reference exists in the input set.

**CONFIG ADDITIONS** (`config.yaml`):
```yaml
grounding:
  synthesis_L3_aggregate_max_tokens: 800
  synthesis_L2_max_tokens: 800
  synthesis_L1_max_tokens: 600
  synthesis_L0_max_tokens: 400
  synthesis_temperature: 0.1
  synthesis_retry_temperature: 0.0
  synthesis_abstain_threshold: 5  # if >N hallucinated names, abstain
```

**ACCEPTANCE**
- After running `synthesize.py --force` on the fixture, no L0/L1/L2 doc references a module that doesn't exist as an input.
- Traceability links appear in all generated L1/L2 docs.
- `context/quality_report.json` includes a `synthesis` section with per-level abstain counts.

**ANTI-PATTERNS**
- Do NOT call `_llm_call` directly from synthesis logic anywhere. Always go through `_llm_call_grounded`.
- Do NOT remove the "strip lines" behavior — it's the cleanup pass that runs BEFORE retry.

---

### T-106 — Enrich `src/rag/ingest.py` with line ranges and content_type

**Mode**: `kip-engineer`
**Effort**: 2 days
**Depends on**: T-101.

**CONTEXT**
For Phase 4 to enforce the citation contract (every MCP tool returns `sources: [{path, line_start, line_end}]`), each chunk needs `line_start` and `line_end` metadata. This is also where we add KIP §3 metadata (block, module, content_type) and the semantic breadcrumb.

**FILES TO MODIFY**

`src/rag/ingest.py`:

1. **CRLF normalization** before chunking AND hashing:
   ```python
   raw = path.read_bytes()
   normalized = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
   text = normalized.decode("utf-8", errors="replace")
   ```

2. **Line-range tracking** per chunk:
   ```python
   def chunk_with_lines(text: str, chunk_size: int, overlap: int) -> list[dict]:
       """Return [{text, line_start, line_end}, ...].

       Use line-based chunking when possible (preserves boundaries), char-based as fallback.
       """
       ...
   ```

3. **Semantic breadcrumb** prepended to chunk text before embedding:
   ```python
   breadcrumb = f"Context: Block={block} | Module={module} | Level={doc_level} | Type={content_type}\n\n"
   embed_text = breadcrumb + chunk["text"]
   ```

4. **Rich metadata** on `collection.add()`:
   ```python
   metadata = {
       "source": str(rel_path),           # path relative to workspace
       "doc_level": doc_level,            # L0|L1|L2|L3|code|config|test
       "block": block_name,               # backend|frontend|infra|... (from codex)
       "module": module_name,
       "content_type": content_type,      # code|codex_doc|synthesis|config|test|changelog
       "line_start": chunk["line_start"],
       "line_end": chunk["line_end"],
       "language": detect_language(path),
       "indexed_at": iso_timestamp,
       "g_version": grounding.G_VERSION,
       "abstained": chunk_meta.get("abstained", False),
   }
   ```

5. **Incremental hashing** (KIP §3.D):
   - Hash each source file MD5(normalized).
   - Store hashes in `context/.ingest_hashes.json`.
   - Skip unchanged files.
   - `--force` flag bypasses the cache.
   - When a file is removed from workspace, remove its chunks from ChromaDB.

**ACCEPTANCE**
- Re-running `python run.py --ingest` on an unchanged workspace logs `0 files re-indexed, N skipped (incremental)`.
- Touching one file → only that file's chunks are deleted+re-added.
- `chroma_client.get(...)` on a chunk returns metadata with all 11 keys above.
- A file with `\r\n` line endings produces the same MD5 as the same file with `\n` line endings.
- Chunk `line_start`/`line_end` correctly map back to source on a hand-checked sample.

**ANTI-PATTERNS**
- Do NOT compute MD5 on raw bytes (CRLF mismatch).
- Do NOT skip incremental on the first run — the hash file should be created on first run, not bypassed.

---

### T-107 — Quality report + golden test harness

**Mode**: `kip-engineer`
**Effort**: 3 days
**Depends on**: T-103, T-105.

**CONTEXT**
We need (a) a programmatic quality report for visibility, and (b) a golden test that prevents regressions. Without these, "no hallucinations" is unverifiable.

**NEW FILE**: `src/rag/quality_report.py`

```python
"""Quality metrics writer for the indexing pipeline.

Reads/writes context/quality_report.json. Thread-safe append.

Schema:
{
  "g_version": "1.0.0",
  "indexed_at": "2026-04-18T...",
  "codex": {
    "total_files": 1234,
    "validation_passed": 1100,
    "validation_failed_then_retried": 100,
    "abstained": 34,
    "files": [
      {"path": "...", "attempts": 2, "abstained": false, "hallucinated_names": [...]},
      ...
    ]
  },
  "synthesis": {
    "L0": {"sections": 1, "abstained": 0, "removed_count": 0},
    "L1": {"sections": 8, "abstained": 0, "removed_count": 3},
    ...
  },
  "ingest": {
    "total_chunks": 9876,
    "skipped_incremental": 9000,
    "added": 876
  }
}
"""

def record_file_quality(path: str, meta: dict) -> None:
    ...

def record_synthesis_quality(level: str, section_id: str, **kwargs) -> None:
    ...

def write_report() -> Path:
    """Flush in-memory report to context/quality_report.json. Return path."""
    ...

def load_report() -> dict:
    ...
```

**NEW FILE**: `tests/golden/test_no_hallucinations.py`

```python
"""Golden test: end-to-end no-hallucination guarantee on a fixture codebase.

The fixture lives at tests/fixtures/mini_workspace/ and contains:
  - 5 Java files with known classes/methods
  - 3 Python files with known functions
  - 1 deliberately confusing file (lots of generic terms)

The test:
  1. Runs codex /scan on the fixture
  2. Runs synthesize.py
  3. Loads the produced docs from context/docs/
  4. For each doc, extracts all identifier-like tokens
  5. Asserts each token is either in the fixture's known identifiers or in the noise filter

Failure mode: this test catches any regression in grounding.
"""

import subprocess
from pathlib import Path
from src.rag.identifiers import extract_identifiers
from src.rag.grounding import load_noise_filter, ABSTAIN_TOKEN, contains_abstain

FIXTURE = Path(__file__).parent.parent / "fixtures" / "mini_workspace"

def test_codex_no_hallucinations(tmp_path, monkeypatch):
    # arrange
    monkeypatch.setenv("WORKSPACE_PATH", str(FIXTURE))
    monkeypatch.setenv("CONTEXT_PATH", str(tmp_path / "context"))

    # act
    subprocess.check_call(["python", "run.py", "--agent", "codex", "--non-interactive", "--scan"])

    # assert
    known = set()
    for f in FIXTURE.rglob("*.java"):
        known |= extract_identifiers(f.read_text(), "java")
    for f in FIXTURE.rglob("*.py"):
        known |= extract_identifiers(f.read_text(), "python")
    noise = load_noise_filter(...)

    docs_dir = tmp_path / "context" / "docs"
    for doc in docs_dir.glob("codex_*.md"):
        text = doc.read_text()
        if contains_abstain(text):
            continue  # abstain is OK
        unknown = _find_unknown_tokens(text, known | noise)
        assert not unknown, f"{doc.name} mentions unknown names: {unknown}"
```

Provide the fixture: 9 small files in `tests/fixtures/mini_workspace/`. Pick from your real codebase (anonymize if needed).

**ACCEPTANCE**
- `pytest tests/golden/test_no_hallucinations.py` runs in <2 minutes and passes.
- The CI workflow (`.gitlab-ci.yml` or `.github/workflows/ci.yml`) includes this test on every push.
- `context/quality_report.json` is generated after each `/scan` and after each `synthesize.py` run.
- A new admin route `/admin/quality` (added in T-108 below) renders the report.

**ANTI-PATTERNS**
- Do NOT mark the test as `xfail` or `skip` to make CI green. Fix the grounding instead.
- Do NOT commit a fixture that includes proprietary code. Use synthetic or anonymized files.

---

### T-108 — Quality dashboard at `/admin/quality`

**Mode**: `roadmap-executor`
**Effort**: 1 day
**Depends on**: T-107.

**CONTEXT**
A simple HTML page that reads `context/quality_report.json` and renders it.

**FILES**

`web/admin_routes.py` (new): expose `GET /admin/quality` that returns the JSON, plus `GET /admin/quality/html` that returns a rendered table.

`web/admin/quality.html` (new): simple template — codex section (totals + table of failing files), synthesis section (per-level table), ingest section (totals).

**ACCEPTANCE**
- After a fresh scan + synthesize, `/admin/quality/html` shows the report.
- The page is linked from the `/admin` landing page (created in T-005).

---

## 4. Phase 1 success gate

Before marking Phase 1 complete and moving to Phase 2/3/4:

- [ ] `tests/golden/test_no_hallucinations.py` passes in CI.
- [ ] On the user's workspace: codex hallucination rate ≤ 2% (measured via quality report).
- [ ] Synthesis docs reference only modules that exist as inputs (verified by traceability link parsing).
- [ ] Incremental ingestion works (re-running on unchanged workspace = 0 re-indexed).
- [ ] `/admin/quality` displays a non-empty report.
- [ ] `G_VERSION` is logged in every codex/synthesis call.

---

## 5. Files Phase 1 produces / modifies

| File | New / Modified |
|------|----------------|
| `src/rag/grounding.py` | NEW |
| `src/rag/identifiers.py` | NEW |
| `src/rag/quality_report.py` | NEW |
| `src/rag/citation_validator.py` | NEW (used in Phase 4 but defined here) |
| `src/agents/codex.py` | MODIFIED |
| `synthesize.py` | MODIFIED |
| `src/rag/ingest.py` | MODIFIED |
| `agents/defs/codex.md` | MODIFIED |
| `config.yaml` | MODIFIED (`grounding.*`, `noise_filter.*`) |
| `requirements.txt` | MODIFIED (tree-sitter packages) |
| `tests/test_grounding.py` | NEW |
| `tests/test_identifiers.py` | NEW |
| `tests/golden/test_no_hallucinations.py` | NEW |
| `tests/fixtures/mini_workspace/` | NEW (9 files) |
| `web/admin_routes.py` | NEW |
| `web/admin/quality.html` | NEW |
| `.roo/skills/grounding.md` | NEW (loaded by `kip-engineer` mode) |

---

*End of Phase 1. The MCP tools shipped from Phase 4 onward depend critically on every task here being executed cleanly. Do not skip the golden test.*
