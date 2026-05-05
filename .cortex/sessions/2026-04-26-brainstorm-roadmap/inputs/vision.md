# Agent Hub — Vision

> The MCP server that gives AI coding agents senior-engineer-level knowledge of your codebase.

## The Problem

Large codebases (100k–10M LOC) contain knowledge distributed across five layers:

1. **Text layer**: Raw source code files
2. **Structure layer**: Module hierarchy, imports, inheritance
3. **Semantics layer**: Meaning, intent, and relationships between components
4. **Conventions layer**: Team-specific patterns and idioms
5. **History layer**: Evolution, rationale, and architectural decisions


Most AI coding agents only see layer 1. They struggle with:
- Understanding architecture and design decisions
- Finding cross-cutting concerns and dependencies
- Discovering team conventions and patterns
- Explaining "why" something was implemented a certain way
- Providing accurate answers about large, unfamiliar codebases

## The Solution

Agent Hub exposes layers 2–5 as structured MCP tools that AI coding agents can query:

- **Code Intelligence**: RAG-augmented Q&A about your codebase
- **Pattern Discovery**: Automated detection of conventions and idioms
- **Architecture Visualization**: Call graphs, dependency maps, and Mermaid diagrams
- **Change Intelligence**: Time-travel changelog with semantic summaries
- **Documentation Automation**: Auto-generated wiki and architecture overview

## Why MCP?

MCP (Model Context Protocol) provides a standardized interface for AI tools:

- **Discoverability**: Clients can list available tools without hardcoding
- **Safety**: Tools declare their inputs and outputs explicitly
- **Integration**: Works with any MCP-compatible client (Roo Code, Continue.dev, Cursor, Cline)
- **Extensibility**: New tools can be added without client changes

## Target Users

### Primary Users
- **AI Coding Agents**: Roo Code, Continue.dev, Cursor, Cline, Claude Code
- **Senior Engineers**: Using Agent Hub to onboard to large unfamiliar codebases
- **Architects**: Querying architecture decisions and cross-cutting concerns

### Secondary Users
- **Tech Leads**: Monitoring codebase evolution through changelogs
- **New Hires**: Getting up to speed on team conventions and patterns
- **Code Reviewers**: Understanding the context behind changes

## Competitive Advantage

Unlike general-purpose RAG systems or code search tools:

| Feature | Agent Hub | Generic RAG | Code Search |
|---------|-----------|-------------|------------|
| Architecture understanding | ✅ | ❌ | ❌ |
| Cross-cutting concern detection | ✅ | ❌ | ❌ |
| Team convention discovery | ✅ | ❌ | ❌ |
| Historical context (changelog) | ✅ | ❌ | ❌ |
| IDE integration via MCP | ✅ | ❌ | ❌ |
| Auto-generated documentation | ✅ | ❌ | ❌ |
| Pattern & convention extraction | ✅ | ❌ | ❌ |
| Call graph visualization | ✅ | ❌ | ❌ |

## Success Metrics

- **Onboarding Time**: Reduce time for new engineers to become productive by 70%
- **Answer Accuracy**: 95%+ of answers must be grounded in source code
- **Query Latency**: <2 seconds for 90% of queries
- **Adoption**: 10+ MCP clients integrated and actively used
- **Documentation Coverage**: 90%+ of codebase documented via auto-generation

## Future Roadmap

### Phase 1: Foundation (Complete)
- MCP server with 29+ tools
- Hybrid search pipeline (vector + AST)
- Documentation pyramid generation
- Web UI for debugging and source citation inspection

### Phase 2: Graph Intelligence (In Progress)
- Knowledge graph integration
- Entity relationship queries
- Impact analysis tools
- Pattern discovery algorithms

### Phase 3: Change Intelligence
- Semantic changelog with entity extraction
- Architecture evolution tracking
- Conventional commit analysis
- Breaking change detection

### Phase 4: MCP Standardization
- Tool schema validation
- Golden tests for all tools
- Performance benchmarks
- Client integration guides

### Phase 5: Advanced Features
- Multi-repo support
- Opt-in telemetry
- Custom pipeline definitions
- IDE-specific integrations

## Open Questions

- How do we handle proprietary codebases with sensitive information?
- What's the performance impact of GraphRAG on large monorepos?
- How can we integrate with existing documentation systems (Confluence, Notion)?
- What's the best way to handle multi-language codebases?
- How do we support teams with multiple simultaneous codebases?

## Non-Goals

- **File Editing**: We don't compete with native IDE editing (Cline, Cursor, etc.)
- **Chat UIs**: We provide MCP tools, not a chat interface (use Open WebUI for that)
- **Project Management**: Greenfield project authoring moved to sister repo `agent-hub-projects`
- **Code Generation**: We focus on knowledge, not implementation generation

---

**Next:** [Architecture Overview](architecture.md) | [MCP Tools Reference](docs/mcp/tools.md)
