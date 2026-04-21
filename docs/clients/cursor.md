# Agent Hub — Cursor Integration Guide

Cursor is an AI coding assistant that works inside VS Code and JetBrains IDEs. To use Agent Hub with Cursor, you need to configure Cursor to connect to Agent Hub's MCP server and use Agent Hub as your LLM provider.

## Prerequisites

- Cursor installed (VS Code or JetBrains IDE)
- Agent Hub running (`docker compose up -d` or `python -m web.server`)
- Agent Hub accessible at `http://localhost:8080`

## Configuration Steps

### Method 1: Using Cursor's MCP Configuration (Recommended)

Cursor supports MCP servers through its settings interface.

#### Step 1: Open Cursor Settings

1. Open Cursor
2. Click the gear icon (⚙️) → "Settings"
3. Search for "MCP Servers"

#### Step 2: Add Agent Hub MCP Server

Add the following configuration:

```json
{
  "mcpServers": {
    "agent-hub": {
      "type": "sse",
      "url": "http://localhost:8080/mcp/sse"
    }
  }
}
```

**File Location:**
- VS Code: `%APPDATA%/Code/User/settings.json` (Windows) or `~/Library/Application Support/Code/User/settings.json` (macOS)
- JetBrains: `~/Library/Application Support/JetBrains/<IDE>/options/mcp.json` (macOS) or `%APPDATA%\JetBrains\<IDE>\options\mcp.json` (Windows)

#### Step 3: Configure LLM Provider

Cursor can use Agent Hub as an OpenAI-compatible provider:

1. Open Cursor settings
2. Search for "API"
3. Configure:

| Setting | Value |
|---------|-------|
| API Type | OpenAI API |
| API Key | *(your `API_KEY` from `.env`)* |
| Base URL | `http://localhost:8080/v1` |
| Model | `expert-rag` |

**Alternative:** Edit settings directly:

```json
{
  "apiType": "openai",
  "apiKey": "your-api-key-here",
  "baseUrl": "http://localhost:8080/v1",
  "model": "expert-rag"
}
```

### Method 2: Using Configuration Files


Cursor supports configuration files for MCP servers.

#### Step 1: Create MCP configuration file

Create a file at `~/.cursor/mcpServers/agent-hub.json` (or `%USERPROFILE%\.cursor\mcpServers\agent-hub.json` on Windows):


```json
{
  "mcpServers": {
    "agent-hub": {
      "type": "sse",
      "url": "http://localhost:8080/mcp/sse"
    }
  }
}
```

#### Step 2: Configure LLM in Cursor

In Cursor settings, configure the LLM provider:

```json
{
  "apiType": "openai",
  "apiKey": "your-api-key-here",
  "baseUrl": "http://localhost:8080/v1",
  "model": "expert-rag"
}
```

## Using Agent Hub with Cursor


### Chat Mode

Cursor chat uses Agent Hub's RAG-augmented expert agent:

```
> Explain how the authentication system works
> What are the main components of the backend API?
> How do I add a new endpoint to the user service?
```

All chat messages go through Agent Hub's full hybrid search pipeline (RAG + GraphRAG).

### Agent Mode (Tools)

Cursor can call Agent Hub tools during agentic tasks:

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

## Troubleshooting

### Cursor can't connect to Agent Hub

1. Verify Agent Hub is running: `curl http://localhost:8080/healthz`
2. Check the API endpoint: `curl http://localhost:8080/v1/models`
3. Verify MCP endpoint: `curl http://localhost:8080/mcp/sse`
4. Check network connectivity between Cursor and Agent Hub
5. Verify firewall settings

### "Model not found" error

1. Check available models: `curl http://localhost:8080/v1/models`
2. Verify you're using `expert-rag` (not `expert`, `documenter`, etc.)
3. Check Agent Hub logs for errors

### Tools not available in Agent Mode

1. Verify MCP configuration is correct in Cursor settings
2. Check that Agent Hub is configured as an MCP server
3. Restart both Cursor and Agent Hub
4. Verify tools are registered in [`src/mcp_server.py`](src/mcp_server.py)

### High latency

1. Check index status: `curl http://localhost:8080/api/stats`
2. Verify ChromaDB is indexed: `ls -la .vectordb/`
3. For large codebases, allow extra time for first query
4. Consider increasing LLM timeout in config

## Advanced Configuration

### Remote Agent Hub

If Agent Hub is running on a remote server:

```json
{
  "mcpServers": {
    "agent-hub": {
      "type": "sse",
      "url": "http://<server-ip>:8080/mcp/sse"
    }
  },
  "baseUrl": "http://<server-ip>:8080/v1"
}
```

### Custom Port

If Agent Hub uses a different port:

```json
{
  "mcpServers": {
    "agent-hub": {
      "type": "sse",
      "url": "http://localhost:9090/mcp/sse"
    }
  },
  "baseUrl": "http://localhost:9090/v1"
}
```

### Multiple MCP Servers

You can configure multiple MCP servers in Cursor:

```json
{
  "mcpServers": {
    "agent-hub": {
      "type": "sse",
      "url": "http://localhost:8080/mcp/sse"
    },
    "another-tool": {
      "type": "stdio",
      "command": "node",
      "args": ["/path/to/tool/index.js"]
    }
  }
}
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
- Configure appropriate model in Cursor settings (`expert-rag`)

## Security Considerations

- Agent Hub respects workspace boundaries (only reads files in `workspace/`)
- File editing tools (`edit_file`) require explicit confirmation
- MCP tools are scoped to the configured workspace
- No telemetry by default (opt-in in Phase 5)

---

**See Also:**
- [Continue.dev Integration Guide](continue.md)
- [Cline Integration Guide](cline.md)
- [Claude Code Integration Guide](claude-code.md)
- [Roo Code Integration Guide](roo-code.md)
- [MCP Tools Reference](../mcp/tools.md)
