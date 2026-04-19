# Skill: Grounding

> Loaded by: `kip-engineer`, `graph-engineer`, `mcp-engineer`.
> Purpose: concrete patterns for writing LLM-calling code that does not hallucinate.

---

## 1. The universal LLM-call template

Every LLM call you write follows this shape:

```python
from src.rag.grounding import (
    prepend_grounding, contains_abstain, ABSTAIN_TOKEN,
)
from src.rag.identifiers import extract_identifiers

def my_grounded_call(input_text: str, llm, config) -> str:
    known_ids = extract_identifiers(input_text, language="java")  # or "python", etc.
    noise = load_noise_filter(config)

    system = prepend_grounding(MY_BASE_SYSTEM_PROMPT)
    for attempt in range(config["grounding"]["max_retries"]):
        out = llm.complete(
            system=system,
            user=input_text,
            temperature=0.1 if attempt == 0 else 0.0,
            max_tokens=config["grounding"]["max_tokens"],
        )
        if contains_abstain(out):
            return out  # honest abstain, preserve
        unknown = validate_names(out, known_ids | noise)
        if not unknown:
            return out  # all names verified
        # tighten prompt for retry
        system = prepend_grounding(
            f"{MY_BASE_SYSTEM_PROMPT}\n\n"
            f"Previous attempt mentioned unknown names: {unknown[:10]}. "
            f"Remove them. If you can't describe the input without these names, "
            f"write {ABSTAIN_TOKEN} and stop."
        )
    # exhausted retries
    return ABSTAIN_TOKEN
```

**Every deviation from this shape is a smell**. If you need to deviate, document why.

---

## 2. Noise filter: what NOT to treat as hallucinations

The validator flags any name in the LLM output that isn't in `known_ids`. But not every unknown name is a hallucination:

- **English words** like "Service", "Controller", "Repository" used as common nouns.
- **Framework terms** like "Spring", "JPA", "JSON", "HTTP" — not project entities.
- **User-added allowlist** from `config.yaml: noise_filter.terms`.

Always pass `known_ids | noise_filter` to the validator, not just `known_ids`. Otherwise the retry rate explodes to 95%.

---

## 3. When to abstain (and make the model do it)

The LLM abstains when:

- The input is too ambiguous to ground a claim.
- The required information is not in the input.
- The model was asked to synthesize across inputs that don't mention the topic.

Make abstain **easy and encouraged**. In your prompts:

> "If any part of your answer cannot be grounded in the input, write `[INSUFFICIENT_EVIDENCE]` for that part and move on. Do not invent plausible text."

Do NOT write:

> "Try your best to answer even if you're not sure."

That phrasing is poison; it gives the model permission to guess.

---

## 4. Validating prose (not just backtick-quoted names)

Hallucinations hide in prose as much as in code blocks. When scanning LLM output:

- Check backtick-quoted tokens: `` `Foo` ``.
- Check CamelCase tokens ≥ 4 chars: `AuthService`.
- Check snake_case tokens ≥ 4 chars: `auth_service`.
- Check dotted paths: `com.example.Foo`, `my.module.bar`.
- Don't check: lowercase-only words (they're English prose).

This is what `_validate_doc()` in codex does. Copy that pattern everywhere you do grounded synthesis.

---

## 5. Token caps are not optional

Long outputs correlate with hallucination. For any grounded LLM call, set `max_tokens` from config:

- Per-file codex: 1500 tokens.
- L3-level synthesis (module aggregate): 800 tokens.
- L2-level synthesis: 800 tokens.
- L1-level synthesis: 600 tokens.
- L0-level synthesis (top-level): 400 tokens.

If the output needs more, the input needs more structure (pre-decompose) or the task needs splitting — not a larger budget.

---

## 6. Logging

Every grounded call logs (structured, JSON):

```json
{"stage": "codex", "file": "path/to/file.java", "attempt": 1,
 "g_version": "1.0.0", "hallucinated_names": [...],
 "abstained": false, "duration_ms": 4200}
```

Never log the prompt or the full output (too noisy + may contain workspace content). Log the metadata.

---

## 7. Anti-patterns summary

| Smell | Fix |
|-------|-----|
| `system_prompt = "You are a helpful assistant..."` (no grounding instruction) | Use `prepend_grounding()`. |
| `temperature=0.7` in indexing | 0.1 first attempt, 0.0 on retry. |
| No validation after generation | Always validate against `known_ids ∪ noise`. |
| Silent retry without tighter prompt | Each retry must include the specific unknown names from the previous attempt. |
| Abstain treated as failure | Abstain is success — preserve the `[INSUFFICIENT_EVIDENCE]` token. |
| Validating only backtick-quoted tokens | Validate CamelCase, snake_case, dotted paths too. |
| No `max_tokens` | Always set one from config. |

---

## 8. Testing grounded code

Every grounded function gets at least 3 tests:

1. **Happy path**: valid input with verifiable names → output clean, no abstain.
2. **Abstain path**: input where the model *should* abstain (unclear, unrelated) → output contains `[INSUFFICIENT_EVIDENCE]` OR is rejected after retries.
3. **Hallucination path**: mock the LLM to return a known-hallucinated name → validator catches it, retry happens, eventually rejected.

Use the golden test at `tests/golden/test_no_hallucinations.py` as the end-to-end sanity check.

---

*End of skill.*
