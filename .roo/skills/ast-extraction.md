# Skill: AST extraction

> Loaded by: `graph-engineer`.
> Purpose: patterns for extracting structural triplets from source code via tree-sitter without inventing anything.

---

## 1. The cardinal rule

**Zero LLM calls in structural extraction.** If you can't determine a fact from the AST, the fact is not extracted. You do not ask a model to "figure it out". Unresolved facts become edges with `confidence: 0.5` — they stay in the graph but are low-trust.

---

## 2. What to extract per language

### Java

| Triplet | AST pattern |
|---------|-------------|
| `Module contains Class` | enclosing `package_declaration` → `class_declaration` |
| `Class extends Class` | `class_declaration.superclass` field |
| `Class implements Interface` | `class_declaration.super_interfaces` field |
| `Class contains Method` | `class_body` → `method_declaration` |
| `Class contains Field` | `class_body` → `field_declaration` |
| `Method calls Method` | walk method body for `method_invocation` nodes |
| `Method reads Field` | `field_access` on RHS |
| `Method writes Field` | `assignment_expression` where LHS is a field |
| `Module imports Module` | `import_declaration` |
| `Class is Service` | `marker_annotation` / `annotation` where name matches `@Service`, `@Component`, `@Controller`, `@Repository` |

### Python

| Triplet | AST pattern |
|---------|-------------|
| `Module contains Class` | file-level `class_definition` |
| `Class extends Class` | `class_definition.bases` |
| `Class contains Method` | `class_definition` → `function_definition` |
| `Module contains Function` | file-level `function_definition` |
| `Function calls Function` | walk function body for `call` nodes (resolve by name) |
| `Module imports Module` | `import_statement` and `import_from_statement` |

### Not supported (Phase 2)

TypeScript, JavaScript, Go, C++, Rust. Fallback to regex. Extend per-language when a real user request demands it.

---

## 3. Walk strategy

Tree-sitter gives you a cursor. Use a plain recursive walk with a **parent stack** so children know their enclosing class/method:

```python
def walk(node, stack):
    if node.type == "class_declaration":
        class_id = make_id("Class", file_path, node.start_point[0])
        stack.append(("Class", class_id))
        emit_node(...)
        emit_edge(source=stack[-2][1], target=class_id, relation="contains")
    # ... similar for method, field
    for child in node.children:
        walk(child, stack)
    if node.type == "class_declaration":
        stack.pop()
```

**Never** try to resolve cross-file references inside the walker. That's the job of the FQN resolver post-pass (T-204).

---

## 4. ID format

Use deterministic IDs so re-running on unchanged files produces the same IDs (essential for incremental updates):

```
Module:  "Module:<dotted_package>"             e.g. "Module:com.example"
Package: "Package:<dotted_package>"            same when a Java package
Class:   "Class:<file_path>:<line>"            e.g. "Class:src/.../Foo.java:42"
Method:  "Method:<class_id>::<method_name>(<arity>)"
Field:   "Field:<class_id>::<field_name>"
```

Collisions: if two methods share name+arity in the same class (overloads), append a counter: `foo(1)#0`, `foo(1)#1`.

---

## 5. Unresolved edges

When walking method bodies, you see calls like `foo()` or `this.bar()`. You don't know if `foo` is:
- a method on the current class,
- an imported static method,
- inherited from a superclass,
- a lambda or local function.

**Don't guess.** Emit an edge with a placeholder target and `confidence: 0.5`:

```python
emit_edge(
    source=current_method_id,
    target=f"UnresolvedCall:{name}",  # placeholder
    relation="calls",
    evidence_path=file_path,
    evidence_line=call_node.start_point[0],
    metadata={"confidence": 0.5, "raw_name": name},
)
```

The resolver pass (T-204) walks imports and intra-package declarations to rewrite these to FQNs. Unresolvable ones keep their placeholder and low confidence.

---

## 6. Performance

- Load the tree-sitter parser once per language, cache in a module-level dict.
- Never load the full AST string-serialize in memory — walk the cursor.
- For a 1MB Java file: target <500ms extraction time.
- For the full user workspace (100k+ files): target <10 minutes, with incremental skip of unchanged files (hash-based).

---

## 7. Testing

Fixtures in `tests/fixtures/ast/`:

- `hello.java` — trivial class with one method.
- `generics.java` — class with generics, static methods.
- `lombok_like.java` — class with annotation-heavy declarations.
- `nested.java` — nested/inner classes.
- `fluent.py` — Python with decorators, dataclasses.
- `asyncio_example.py` — async defs.

Each fixture has a **snapshot** of expected nodes and edges in `tests/fixtures/ast/expected/`. Snapshot tests are brittle — but for AST extraction, brittleness is a feature: if the extractor's behavior changes, we want to see the diff and decide if it's correct.

---

## 8. When AST fails

Tree-sitter parsers are tolerant but not infinite. On parse errors:

1. Log the file path + error, once per file (not per call).
2. Fall back to regex extraction (via `src/rag/identifiers.py: extract_identifiers(..., language=None)`).
3. Tag all emitted edges with `metadata: {fallback: "regex"}`.
4. Continue.

Do NOT crash the full indexing run on one bad file.

---

## 9. Anti-patterns

| Smell | Fix |
|-------|-----|
| Calling an LLM to "figure out" what a class does structurally | Use AST. LLM is for enrichment only (descriptions, not structure). |
| Extracting every identifier as a node | Only declaration nodes become nodes. Body tokens become edges from the enclosing method. |
| Throwing away unresolved calls | Keep them with `confidence: 0.5`. Low confidence > no data. |
| Re-running the extractor on every file every time | Incremental: hash source, skip unchanged files. `store.delete_for_file()` before re-extracting a changed file. |
| Storing AST in the graph DB | No. Store node/edge records only. |

---

*End of skill.*
