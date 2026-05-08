"""Per-commit semantic enrichment.

For each commit, produces a structured summary:
    {
        "intent": "feature|fix|refactor|chore|docs|test|unknown",
        "summary": "1-2 sentence narrative",
        "modules_affected": ["src/auth", "src/web"],
        "risk_score": 0.6,
    }

Grounded with Phase 1's GROUNDING_INSTRUCTION + temperature 0.1.
Hallucinated modules → reject and retry once, then abstain.

Risk score heuristic (deterministic, no LLM):
    - +0.3 if touches >5 files
    - +0.2 if touches a hub module (from graph store)
    - +0.2 if touches a config file
    - +0.1 per 100 net lines changed (capped at 0.4)
    - 0.0 baseline
    Capped at 1.0.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from src.rag.grounding import ABSTAIN_TOKEN, prepend_grounding
from src.temporal.git_client import Commit, FileChange
from src.temporal.store import TemporalStore

logger = logging.getLogger(__name__)

ALLOWED_INTENTS = {"feature", "fix", "refactor", "chore", "docs", "test", "unknown"}

# Default enrichment prompt — used when no graph_store is available.
_ENRICHMENT_PROMPT = """\
You are a technical changelog writer for a development team. Your task is to \
summarize a single git commit concisely and accurately.

Files changed:
{files}

Commit message:
{subject}

{body_section}

Diff (may be truncated):
{diff}

Produce STRICT JSON (no markdown, no code fences, no extra text):
{{
  "intent": "feature|fix|refactor|chore|docs|test|unknown",
  "summary": "1-2 sentence narrative, max 200 chars",
  "modules_affected": ["module1", "module2"]
}}

Rules:
- Use ONLY module names that appear as path prefixes in the files list.
- Do NOT invent class names, design intentions, or features.
- If the commit's purpose is unclear from the inputs, return intent=unknown \
and summary=[INSUFFICIENT_EVIDENCE].
- Keep the summary factual and brief.
"""


def enrich_commit(
    commit: Commit,
    files: List[FileChange],
    diff_text: str,
    *,
    llm_client: Any,
    config: Dict,
    graph_store: Any = None,
) -> Dict[str, Any]:
    """Enrich a single commit with semantic metadata.

    Args:
        commit: The Commit object.
        files: List of FileChange objects for this commit.
        diff_text: The unified diff text (may be truncated).
        llm_client: OpenAI-compatible chat client with .chat() method.
        config: Application config dict (contains grounding settings).
        graph_store: Optional graph store for hub-module detection.

    Returns:
        Dict with keys: intent, summary, modules_affected, risk_score, g_version.
    """
    # Build the prompt
    body_section = ""
    if commit.body:
        body_section = f"Commit body:\n{commit.body}\n"

    files_list = "\n".join(f"- {f.path} ({f.status})" for f in files)

    prompt = _ENRICHMENT_PROMPT.format(
        files=files_list,
        subject=commit.subject,
        body_section=body_section,
        diff=diff_text[:5000] if diff_text else "(no diff available)",
    )

    # Ground the prompt
    grounded_system = prepend_grounding(
        "You are summarizing a single git commit. Produce only JSON output."
    )

    # Get model config
    grounding_cfg = config.get("grounding", {})
    model = config.get("models", {}).get("heavy", "gpt-4o")
    temperature = grounding_cfg.get("synthesis_temperature", 0.1)
    max_tokens = grounding_cfg.get("synthesis_L1_max_tokens", 4096)

    # Attempt 1
    result = _try_enrich(grounded_system, prompt, llm_client, model, temperature, max_tokens)

    # Retry once on failure
    if result["intent"] == "unknown" and result["summary"] == ABSTAIN_TOKEN:
        retry_system = prepend_grounding(
            "You are summarizing a single git commit. "
            f"Your previous attempt failed. If you cannot produce a grounded summary, "
            f"return intent=unknown and summary=[INSUFFICIENT_EVIDENCE]. Do not invent names."
        )
        result = _try_enrich(
            retry_system, prompt, llm_client, model, 0.0, max_tokens
        )

    # Compute risk score (deterministic)
    result["risk_score"] = _compute_risk_score(
        files, graph_store=graph_store
    )

    return result


def _try_enrich(
    system: str,
    user: str,
    llm_client: Any,
    model: str,
    temperature: float,
    max_tokens: int,
) -> Dict[str, Any]:
    """Make an LLM call and parse the JSON response.

    Returns:
        Dict with intent, summary, modules_affected (and risk_score=0.0 placeholder).
    """
    try:
        response = llm_client.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        logger.warning(f"[Enricher] LLM call failed: {e}")
        return {
            "intent": "unknown",
            "summary": ABSTAIN_TOKEN,
            "modules_affected": [],
            "risk_score": 0.0,
        }

    # Parse JSON from response (strip markdown fences if present)
    text = response.strip()
    # Remove ```json ... ``` or ``` ... ``` fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"[Enricher] JSON parse failed: {e}")
        return {
            "intent": "unknown",
            "summary": ABSTAIN_TOKEN,
            "modules_affected": [],
            "risk_score": 0.0,
        }

    # Validate and normalize
    intent = data.get("intent", "unknown")
    if intent not in ALLOWED_INTENTS:
        intent = "unknown"

    summary = data.get("summary", "")
    if not summary or not isinstance(summary, str):
        summary = ABSTAIN_TOKEN

    modules = data.get("modules_affected", [])
    if not isinstance(modules, list):
        modules = []
    # Ensure all modules are strings
    modules = [m for m in modules if isinstance(m, str) and m]

    return {
        "intent": intent,
        "summary": summary,
        "modules_affected": modules,
        "risk_score": 0.0,  # computed later
    }


def _compute_risk_score(
    files: List[FileChange],
    *,
    graph_store: Any = None,
) -> float:
    """Compute a deterministic risk score for a commit.

    Heuristic:
        - +0.3 if touches >5 files
        - +0.2 if touches a hub module (from graph store)
        - +0.2 if touches a config file
        - +0.1 per 100 net lines changed (capped at 0.4)
        - 0.0 baseline
        Capped at 1.0.

    Args:
        files: List of FileChange objects.
        graph_store: Optional graph store for hub-module detection.

    Returns:
        Float in [0, 1].
    """
    score = 0.0

    # +0.3 if touches >5 files
    if len(files) > 5:
        score += 0.3

    # +0.2 if touches a hub module
    if graph_store is not None:
        for fc in files:
            module_path = _extract_module_path(fc.path)
            if _is_hub_module(graph_store, module_path):
                score += 0.2
                break

    # +0.2 if touches a config file
    config_extensions = {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".env"}
    config_file_names = {"dockerfile", "docker-compose", ".gitlab-ci", "jenkinsfile"}
    for fc in files:
        path_lower = fc.path.lower().replace("\\", "/")
        _, ext = _split_ext(path_lower)
        # Use string manipulation instead of Path for cross-platform consistency
        file_name = path_lower.rsplit("/", 1)[-1].lower()
        if ext in config_extensions or file_name in config_file_names:
            score += 0.2
            break

    # +0.1 per 100 net lines changed (capped at 0.4)
    net_lines = sum(fc.insertions for fc in files) - sum(fc.deletions for fc in files)
    net_lines = max(0, net_lines)
    score += min(0.4, (net_lines / 100) * 0.1)

    return min(1.0, round(score, 2))


def _extract_module_path(filepath: str) -> str:
    """Extract the module path prefix from a file path.

    Args:
        filepath: File path (e.g. "src/auth/login.py").

    Returns:
        Module path (e.g. "src/auth").
    """
    # Normalize Windows paths to forward slashes
    normalized = filepath.replace("\\", "/")
    parts = normalized.split("/")
    if len(parts) <= 2:
        return parts[0] if parts else ""
    return "/".join(parts[:2])


def _is_hub_module(graph_store: Any, module_path: str) -> bool:
    """Check if a module is a hub module (high-degree node) in the graph.

    Args:
        graph_store: Graph store instance.
        module_path: Module path to check.

    Returns:
        True if the module is a hub, False otherwise.
    """
    try:
        # Check if the graph store has a method to detect hub nodes
        if hasattr(graph_store, "is_hub"):
            return graph_store.is_hub(module_path)
        # Fallback: check if the module has many connections
        if hasattr(graph_store, "get_node"):
            node = graph_store.get_node(module_path)
            if node and hasattr(node, "degree"):
                return node.degree > 10
    except Exception:
        pass
    return False


def _split_ext(filepath: str) -> tuple:
    """Split a filepath into (path_without_ext, extension).

    Args:
        filepath: File path (e.g. "src/main.py").

    Returns:
        Tuple of (path, ext) (e.g. ("src/main", ".py")).
    """
    # Normalize to forward slashes for consistent cross-platform behavior
    normalized = filepath.replace("\\", "/")
    from pathlib import Path
    p = Path(normalized)
    return str(p.with_suffix("")).replace("\\", "/"), p.suffix.lower()


def enrich_pending(
    store: TemporalStore,
    *,
    llm_client: Any,
    config: Dict,
    graph_store: Any = None,
    max_diff_lines: int = 2000,
) -> int:
    """Enrich all unenriched commits in the store.

    This is the main entry point for batch enrichment. It:
    1. Queries the store for unenriched commits.
    2. For each commit, fetches the diff from git.
    3. Calls enrich_commit() to get semantic metadata.
    4. Stores the enrichment back in the database.

    Args:
        store: TemporalStore instance.
        llm_client: OpenAI-compatible chat client.
        config: Application config dict.
        graph_store: Optional graph store for hub-module detection.
        max_diff_lines: Maximum diff lines to fetch per commit.

    Returns:
        Number of commits enriched.
    """
    unenriched_shas = store.all_unenriched(limit=100)
    if not unenriched_shas:
        logger.info("[Enricher] No unenriched commits to process.")
        return 0

    logger.info(f"[Enricher] Enriching {len(unenriched_shas)} unenriched commit(s)...")
    enriched_count = 0

    for sha in unenriched_shas:
        try:
            # Get commit data from store
            commit_data = store.get_commit(sha)
            if not commit_data:
                logger.warning(f"[Enricher] Commit {sha[:7]} not found in store, skipping.")
                continue

            # Reconstruct Commit object
            commit = Commit(
                sha=commit_data["sha"],
                author=commit_data["author"],
                date=commit_data["date"],
                subject=commit_data["subject"],
                body=commit_data.get("body", ""),
            )

            # Get files changed
            files = [
                FileChange(**f) for f in commit_data.get("files", [])
            ]

            # Fetch diff
            from src.temporal.git_client import diff_for_commit
            diff_text = diff_for_commit(sha, max_lines=max_diff_lines)

            # Enrich
            result = enrich_commit(
                commit, files, diff_text,
                llm_client=llm_client,
                config=config,
                graph_store=graph_store,
            )

            # Store enrichment
            store.set_enrichment(
                sha,
                intent=result["intent"],
                summary=result["summary"],
                modules_affected=result["modules_affected"],
                risk_score=result["risk_score"],
                g_version="1.0.0",  # Will be updated when grounding.py versioning is added
            )

            enriched_count += 1
            logger.debug(
                f"[Enricher] Enriched {sha[:7]}: intent={result['intent']}, "
                f"risk={result['risk_score']}"
            )

        except Exception as e:
            logger.error(f"[Enricher] Failed to enrich {sha[:7]}: {e}", exc_info=True)
            continue

    logger.info(f"[Enricher] Enriched {enriched_count}/{len(unenriched_shas)} commits.")
    return enriched_count
