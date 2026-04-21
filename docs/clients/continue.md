# Agent Hub — Continue.dev Integration Guide

Continue.dev is an AI coding assistant that works inside VS Code, JetBrains IDEs, and other editors. To use Agent Hub with Continue.dev, you need to configure Continue.dev to connect to Agent Hub's MCP server and use Agent Hub as your LLM provider.

## Prerequisites

- Continue.dev extension installed in your IDE
- Agent Hub running (`docker compose up -d` or `python -m web.server`)
- Agent Hub accessible at `http://localhost:8080`

## Configuration Steps

### Step 1: Configure MCP Tools

Continue.dev uses MCP tools for agentic tasks. Configure Agent Hub as an MCP server.

#### Method A: Using Configuration Files (Recommended)

1. Create the Continue.dev configuration directory if it doesn't exist:

```bash
# VS Code
mkdir -p .continue/mcpServers

# JetBrains (IntelliJ, PyCharm, etc.)
# Configuration is typically in IDE settings, but you can use project-level config
```

2. Copy the provided configuration file:

```bash
cp continue-sse.yaml .continue/mcpServers/agent-hub.yaml
```

3. If Agent Hub is running on a different host or port, edit the file:

```yaml
mcpServers:
  agent-hub:
    type: sse
    url: http://localhost:8080/mcp/sse
```

#### Method B: Using Continue.dev Settings UI

1. Open Continue.dev settings in your IDE
2. Navigate to "MCP Servers" section
3. Add a new MCP server:
   - Name: `agent-hub`
   - Type: `sse`
   - URL: `http://localhost:8080/mcp/sse`

### Step 2: Configure LLM Provider

Continue.dev needs to use Agent Hub as an OpenAI-compatible LLM provider.

#### Method A: Using Configuration Files

Edit your `.continue/config.yaml` file:

```yaml
models:
  - title: Agent Hub — Expert RAG
    provider: openai
    model: expert-rag
    apiBase: http://localhost:8080/v1
    apiKey: your-api-key-here
```

**Note:** Replace `your-api-key-here` with your actual API key from `.env`

#### Method B: Using Continue.dev Settings UI

1. Open Continue.dev settings
2. Navigate to "Models" section
3. Add a new model:
   - Provider: `OpenAI`
   - Model: `expert-rag`
   - API Base: `http://localhost:8080/v1`
   - API Key: *(your API key)*

## Using Agent Hub with Continue.dev

### Chat Mode

Continue.dev chat uses Agent Hub's RAG-augmented expert agent:

```
> Explain how the authentication system works
> What are the main components of the backend API?
> How do I add a new endpoint to the user service?
```

All chat messages go through Agent Hub's full hybrid search pipeline (RAG + GraphRAG).

### Agent Mode (Tools)

Continue.dev can call Agent Hub tools during agentic tasks:

```
> Use expert_ask to explain the UserService class
> Search the RAG index for database migration patterns
> What does search_graph say about dependencies of UserService?
> List deliverables for project my-feature
```

**Available Tools:**
- `expert_ask` — RAG-powered code Q&A
- `search_rag` — Search the vector index directly
- `search_graph` — Entity relationships and dependency queries
- `read_file` / `edit_file` — Browse and edit workspace files
- `list_deliverables` / `read_deliverable` / `apply_deliverable` — Project deliverables
- `call_graph` — Generate call graphs
- `discover_patterns` — Discover team conventions

### Example Workflows

**Code Review:**
```
> Review the changes in my recent commit
> Use expert_ask to analyze the security implications
> Use search_graph to find all authentication-related components
> Use impact_preview to see what else might be affected
```

**Onboarding:**
```
> Explain the architecture of the backend API
> Use search_rag to find documentation about the main modules
> Use call_graph to visualize the request flow
> Use discover_patterns to understand team conventions
```

**Debugging:**
```
> The UserService is throwing a NullPointerException
> Use expert_ask with the error trace to find the root cause
> Use read_file to check the UserService implementation
> Use search_rag to find similar issues in the codebase
```

## Configuration Files

### Provided Configuration Files

Agent Hub provides two pre-configured files:


1. **continue-sse.yaml** (root directory)
   - Configures Agent Hub as an SSE MCP server
   - Ready to use, just copy to `.continue/mcpServers/`

2. **continue-stdio.yaml** (root directory)
   - Configures Agent Hub as a stdio MCP server
   - Useful for local development without Docker
   - Requires Python environment setup

### continue-sse.yaml Example

```yaml
mcpServers:
  agent-hub:
    type: sse
    url: http://localhost:8080/mcp/sse
```

### continue-stdio.yaml Example

```yaml
mcpServers:
  agent-hub:
    type: stdio
    command: python
    args:
      - -m
      - src.mcp_server
    cwd: /path/to/agent-hub
    env:
      PYTHONPATH: /path/to/agent-hub
```

**Note:** Replace `/path/to/agent-hub` with your actual Agent Hub directory path.

## Troubleshooting

### Continue.dev can't connect to Agent Hub

1. Verify Agent Hub is running: `curl http://localhost:8080/healthz`
2. Check the API endpoint: `curl http://localhost:8080/v1/models`
3. Verify MCP endpoint: `curl http://localhost:8080/mcp/sse`
4. Check network connectivity between Continue.dev and Agent Hub
5. Verify firewall settings

### "Model not found" error

1. Check available models: `curl http://localhost:8080/v1/models`
2. Verify you're using `expert-rag` (not `expert`, `documenter`, etc.)
3. Check Agent Hub logs for errors

### Tools not available in Agent Mode

1. Verify MCP configuration is correct in `.continue/config.yaml`
2. Check that Agent Hub is configured as an MCP server in `.continue/mcpServers/`
3. Restart Continue.dev
4. Verify tools are registered in [`src/mcp_server.py`](src/mcp_server.py)

### High latency

1. Check index status: `curl http://localhost:8080/api/stats`
2. Verify ChromaDB is indexed: `ls -la .vectordb/`
3. For large codebases, allow extra time for first query
4. Consider increasing LLM timeout in config

## Advanced Configuration

### Remote Agent Hub

If Agent Hub is running on a remote server:

```yaml
# .continue/mcpServers/agent-hub.yaml
mcpServers:
  agent-hub:
    type: sse
    url: http://<server-ip>:8080/mcp/sse

# .continue/config.yaml
models:
  - title: Agent Hub — Expert RAG
    provider: openai
    model: expert-rag
    apiBase: http://<server-ip>:8080/v1
    apiKey: your-api-key-here
```

### Custom Port

If Agent Hub uses a different port:

```yaml
# .continue/mcpServers/agent-hub.yaml
mcpServers:
  agent-hub:
    type: sse
    url: http://localhost:9090/mcp/sse

# .continue/config.yaml
models:
  - title: Agent Hub — Expert RAG
    provider: openai
    model: expert-rag
    apiBase: http://localhost:9090/v1
    apiKey: your-api-key-here
```

### Multiple Models

You can configure multiple models in Continue.dev:

```yaml
# .continue/config.yaml
models:
  - title: Agent Hub — Expert RAG
    provider: openai
    model: expert-rag
    apiBase: http://localhost:8080/v1
    apiKey: your-api-key-here
  - title: Local Llama
    provider: llamacpp
    model: llama-3-8b
    apiBase: http://localhost:8000
```

## Best Practices

1. **Use specific queries**: The more specific your query, the better Agent Hub can ground the answer
2. **Check sources**: Always review the source citations provided by Agent Hub
3. **Combine tools**: Use multiple Agent Hub tools together for complex tasks
4. **Iterative refinement**: Start with broad queries, then refine based on results
5. **Use Agent Mode for tools**: MCP tools only work in Agent Mode, not Chat Mode

## Performance Tips

- Agent Hub performs best with a pre-built index (run `python run.py --ingest` after setup)
- For large codebases, allow extra time for the first query (index loading)
- Use `search_rag` for quick lookups, `expert_ask` for complex questions
- Configure appropriate model in Continue.dev settings (`expert-rag`)

## Security Considerations

- Agent Hub respects workspace boundaries (only reads files in `workspace/`)
- File editing tools (`edit_file`) require explicit confirmation
- MCP tools are scoped to the configured workspace
- No telemetry by default (opt-in in Phase 5)

---

**See Also:**
- [Cline Integration Guide](cline.md)
- [Claude Code Integration Guide](claude-code.md)
- [Roo Code Integration Guide](roo-code.md)
- [Cursor Integration Guide](cursor.md)
- [MCP Tools Reference](../mcp/tools.md)
