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

from src.rag.grounding import load_noise_filter, ABSTAIN_TOKEN, contains_abstain
from src.rag.identifiers import extract_identifiers

FIXTURE = Path(__file__).parent.parent / "fixtures" / "mini_workspace"


def _find_unknown_tokens(text: str, known: set[str], noise: frozenset[str]) -> list[str]:
    """Find tokens in text that are not in known or noise."""
    import re
    
    # Built-in stopword list to avoid false positives on common English words
    STOPWORDS = frozenset({
        "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
        "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
        "this", "but", "his", "by", "from", "they", "we", "say", "her", "she",
        "or", "an", "will", "my", "one", "all", "would", "there", "their", "what",
        "so", "up", "out", "if", "about", "who", "get", "which", "go", "me",
        "when", "make", "can", "like", "time", "no", "just", "him", "know",
        "take", "people", "into", "year", "your", "good", "some", "could", "them",
        "see", "other", "than", "then", "now", "look", "only", "come", "its", "over",
        "think", "also", "back", "after", "use", "two", "how", "our", "work", "first",
        "well", "way", "even", "new", "want", "because", "any", "these", "give", "day",
        "most", "us", "is", "are", "was", "were", "has", "had", "been", "being",
    })
    
    candidates: set[str] = set()
    
    # 1. Backtick-quoted tokens
    backtick_matches = re.findall(r'`([^`]+)`', text)
    candidates.update(backtick_matches)
    
    # 2. CamelCase tokens >= 4 chars (at least 2 humps: MyClass, not My)
    camel_matches = re.findall(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b', text)
    candidates.update(c for c in camel_matches if len(c) >= 4)
    
    # 3. snake_case tokens >= 4 chars
    snake_matches = re.findall(r'\b([a-z_][a-z0-9_]{3,})\b', text)
    candidates.update(s for s in snake_matches if len(s) >= 4)
    
    # 4. dotted paths (e.g., com.example.Foo, my.module.bar)
    dotted_matches = re.findall(r'\b([a-z0-9_]+(?:\.[a-z0-9_]+)+)\b', text, re.IGNORECASE)
    candidates.update(d for d in dotted_matches if len(d) >= 4)
    
    # Filter: keep only those not in known, not in noise, and not a stopword
    unknown = []
    for cand in candidates:
        if cand.lower() in STOPWORDS:
            continue
        if cand in known or cand in noise:
            continue
        unknown.append(cand)
    
    return unknown


def test_codex_no_hallucinations(tmp_path, monkeypatch):
    """Test that codex generates docs without hallucinations."""
    # arrange
    monkeypatch.setenv("WORKSPACE_PATH", str(FIXTURE))
    monkeypatch.setenv("CONTEXT_PATH", str(tmp_path / "context"))
    
    # act: run codex scan
    subprocess.check_call([
        "python", "-m", "src.main", "--agent", "codex", "--ingest", "--verbose"
    ])
    
    # Load known identifiers from fixture
    known = set()
    for f in FIXTURE.rglob("*.java"):
        known |= extract_identifiers(f.read_text(), "java")
    for f in FIXTURE.rglob("*.py"):
        known |= extract_identifiers(f.read_text(), "python")
    
    # Load noise filter from config
    config_path = Path("config.yaml")
    if config_path.exists():
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        noise = load_noise_filter(config)
    else:
        noise = load_noise_filter({})
    
    # assert: check all codex docs
    docs_dir = tmp_path / "context" / "docs"
    assert docs_dir.exists(), f"Docs directory not found at {docs_dir}"
    
    failed_docs = []
    for doc in docs_dir.glob("codex_*.md"):
        text = doc.read_text()
        if contains_abstain(text):
            continue  # abstain is OK
        unknown = _find_unknown_tokens(text, known, noise)
        if unknown:
            failed_docs.append({
                "doc": doc.name,
                "unknown": unknown,
                "path": str(doc),
            })
    
    assert not failed_docs, (
        f"Found hallucinated names in {len(failed_docs)} docs:\n"
        + "\n".join([
            f"  {d['doc']}: {d['unknown']}" for d in failed_docs
        ])
    )


def test_synthesis_no_hallucinations(tmp_path, monkeypatch):
    """Test that synthesis generates docs without hallucinations."""
    # arrange
    monkeypatch.setenv("WORKSPACE_PATH", str(FIXTURE))
    monkeypatch.setenv("CONTEXT_PATH", str(tmp_path / "context"))
    
    # act: run codex scan first
    subprocess.check_call([
        "python", "run.py", "--agent", "codex", "--non-interactive", "--scan"
    ])
    
    # act: run synthesis
    subprocess.check_call([
        "python", "synthesize.py", "--force", "--verbose"
    ])
    
    # Load known identifiers from fixture
    known = set()
    for f in FIXTURE.rglob("*.java"):
        known |= extract_identifiers(f.read_text(), "java")
    for f in FIXTURE.rglob("*.py"):
        known |= extract_identifiers(f.read_text(), "python")
    
    # Load noise filter from config
    config_path = Path("config.yaml")
    if config_path.exists():
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        noise = load_noise_filter(config)
    else:
        noise = load_noise_filter({})
    
    # assert: check all synthesis docs
    docs_dir = tmp_path / "context" / "docs"
    assert docs_dir.exists(), f"Docs directory not found at {docs_dir}"
    
    failed_docs = []
    for doc in docs_dir.glob("synth_*.md"):
        text = doc.read_text()
        if contains_abstain(text):
            continue  # abstain is OK
        unknown = _find_unknown_tokens(text, known, noise)
        if unknown:
            failed_docs.append({
                "doc": doc.name,
                "unknown": unknown,
                "path": str(doc),
            })
    
    assert not failed_docs, (
        f"Found hallucinated names in {len(failed_docs)} synthesis docs:\n"
        + "\n".join([
            f"  {d['doc']}: {d['unknown']}" for d in failed_docs
        ])
    )
