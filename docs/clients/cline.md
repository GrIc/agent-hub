# Agent Hub — Cline Integration Guide

Cline is an AI coding assistant that works inside VS Code. To use Agent Hub with Cline, you need to configure Cline to connect to Agent Hub's MCP server.

## Prerequisites

- Cline extension installed in VS Code
- Agent Hub running (`docker compose up -d` or `python -m web.server`)
- Agent Hub accessible at `http://localhost:8080/mcp/sse`

## Configuration Steps

### 1. Open Cline Settings

1. Open VS Code
2. Click the Cline icon in the sidebar (or press `Ctrl+Shift+P`)
3. Click the gear icon (⚙️) → "Settings"

### 2. Add Agent Hub as an MCP Server

In Cline's MCP settings, add the following configuration:

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
- Windows: `%APPDATA%/Code/User/globalStorage/cline.cline/settings.json`
- macOS: `~/Library/Application Support/Code/User/globalStorage/cline.cline/settings.json`
- Linux: `~/.config/Code/User/globalStorage/cline.cline/settings.json`

### 3. Restart Cline

After saving the configuration, restart Cline for the changes to take effect.

## Using Agent Hub Tools in Cline

Once configured, Cline can call Agent Hub tools during agentic tasks:

```
> Use expert_ask to explain how the authentication module works
> Search the RAG index for database migration patterns
> What does search_graph say about dependencies of UserService?
> List deliverables for project my-feature
```

### Example Prompts

**Code Q&A:**
```
"Explain how the authentication system works using expert_ask"
```

**Search:**
```
"Find all files that reference the User model"
```

**Graph Analysis:**
```
"Show me the call graph for the checkout function"
```

**Project Management:**
```
"List all deliverables for the checkout feature"
```

## Troubleshooting

### Agent Hub not showing in Cline

1. Verify Agent Hub is running: `curl http://localhost:8080/healthz`
2. Check MCP SSE endpoint: `curl http://localhost:8080/mcp/sse`
3. Verify Cline settings file path and permissions
4. Restart VS Code and Cline

### Connection refused

1. Check Agent Hub is listening: `netstat -ano | findstr 8080` (Windows) or `lsof -i :8080` (macOS/Linux)
2. Verify network connectivity between Cline and Agent Hub
3. Check firewall settings

### Tool not found

1. Verify tool exists: `curl http://localhost:8080/mcp/sse | grep "tool/"`
2. Check Agent Hub logs for errors: `docker compose logs web`
3. Restart Agent Hub container

## Advanced Configuration

### Remote Development

If Agent Hub is running on a remote machine:

```json
{
  "mcpServers": {
    "agent-hub": {
      "type": "sse",
      "url": "http://<remote-ip>:8080/mcp/sse"
    }
  }
}
```

### Custom Port

If Agent Hub is running on a different port:

```json
{
  "mcpServers": {
    "agent-hub": {
      "type": "sse",
      "url": "http://localhost:9090/mcp/sse"
    }
  }
}
```

## Best Practices

1. **Use specific queries**: The more specific your query, the better Agent Hub can ground the answer
2. **Check sources**: Always review the source citations provided by Agent Hub
3. **Combine tools**: Use multiple Agent Hub tools together (e.g., `search_rag` + `expert_ask`)
4. **Iterative refinement**: Start with broad queries, then refine based on results

## Performance Tips

- Agent Hub performs best with a pre-built index (run `python run.py --ingest` after setup)
- For large codebases, allow extra time for the first query (index loading)
- Use `search_rag` for quick lookups, `expert_ask` for complex questions

---

**See Also:**
- [Continue.dev Integration Guide](continue.md)
- [Claude Code Integration Guide](claude-code.md)
- [Roo Code Integration Guide](roo-code.md)
- [Cursor Integration Guide](cursor.md)
- [MCP Tools Reference](../mcp/tools.md)
