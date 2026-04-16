# Agent Hub Development Rules

## Code Standards
- All code, comments, docstrings, log messages, and prompts MUST be in English.
- No French in any generated file. User-facing CLI messages are in English.
- Use type hints for all function signatures.
- Use `logging` module, never `print()` for diagnostics.

## Anti-Hallucination Rules
- Every LLM prompt in this codebase MUST include grounding instructions from `src/rag/grounding.py`.
- Every LLM output that references code entities MUST be validated against known identifiers.
- Temperature for factual/extraction tasks: 0.0–0.1. Temperature for creative/summary tasks: 0.3 max.
- Never trust LLM output as ground truth. Always cross-reference against source files.

## Architecture Rules
- Do NOT create new files unless explicitly required by the task. Prefer modifying existing files.
- Do NOT add new Python dependencies without explicit approval.
- All configuration belongs in `config.yaml`, never hardcoded.
- Delivery format: complete file replacements, not diffs or patches.

## Testing
- After modifying any file in the indexing pipeline, test with a small module (10-20 source files).
- Check that no hallucinated names appear in generated docs.
- Check that `--force` flags work and incremental mode skips unchanged files.
