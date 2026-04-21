# Agent Hub — Claude Code Integration Guide

Claude Code is Anthropic's AI coding assistant that runs in your terminal. Agent Hub integrates with Claude Code via MCP (Model Context Protocol) in two modes: SSE (server) and stdio (subprocess).

## Prerequisites

- Claude Code installed
- Agent Hub running (`docker compose up -d` or `python -m web.server`)
- Agent Hub accessible at `http://localhost:8080/mcp/sse`

## Configuration Methods

### Method 1: SSE Mode (Recommended)

Claude Code connects to Agent Hub running as a server.

#### Step 1: Add to Claude Code settings

Edit your `~/.claude/settings.json` file (create it if it doesn't exist):

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

**File Locations:**
- macOS/Linux: `~/.claude/settings.json`
- Windows: `%USERPROFILE%/.claude/settings.json`

#### Step 2: Verify Agent Hub is running

```bash
# Check health
curl http://localhost:8080/healthz

# Check MCP endpoint
curl http://localhost:8080/mcp/sse
```

#### Step 3: Test connection

Start Claude Code and try:
```
> Use expert_ask to explain how the authentication module works
> Search the RAG index for database migration patterns
```

### Method 2: Stdio Mode

Claude Code spawns Agent Hub as a subprocess (useful for local development without Docker).

#### Step 1: Add to settings

```json
{
  "mcpServers": {
    "agent-hub": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/path/to/agent-hub",
      "env": {
        "PYTHONPATH": "/path/to/agent-hub"
      }
    }
  }
}
```

**Important:** Replace `/path/to/agent-hub` with the actual path to your Agent Hub repository.

#### Step 2: Verify Python environment

Ensure you have all dependencies installed:
```bash
pip install -r requirements.txt
```

#### Step 3: Test connection

Start Claude Code and try:
```
> Use expert_ask to explain the UserService class
> What dependencies does the AuthMiddleware have?
```

## Using Agent Hub Tools in Claude Code

Once configured, you can use Agent Hub tools in any agentic session:

```
> Use expert_ask to explain how the payment processing works
> Search the RAG index for all files that import the User model
> Generate a call graph for the checkout function
> List deliverables for the checkout feature project
```

### Example Sessions

**Code Review Session:**
```
> I need to review the authentication changes in PR #123
> Use expert_ask to analyze the security implications
> Use search_graph to find all authentication-related components
> Use impact_preview to see what else might be affected
```

**Onboarding Session:**
```
> Explain the architecture of the backend API
> Use search_rag to find documentation about the main modules
> Use call_graph to visualize the request flow
> Use discover_patterns to understand team conventions
```

**Debugging Session:**
```
> The UserService is throwing a NullPointerException
> Use expert_ask with the error trace to find the root cause
> Use read_file to check the UserService implementation
> Use search_rag to find similar issues in the codebase
```

## Configuration Files

### Ready-to-Use Config (claude-code-mcp.json)

A pre-configured file is provided at the root of the Agent Hub repository:

```bash
# Copy to your Claude Code settings directory
cp claude-code-mcp.json ~/.claude/settings.json
```

Then edit the `cwd` field to point to your Agent Hub directory.

## Troubleshooting

### "Connection refused" error

1. Verify Agent Hub is running: `curl http://localhost:8080/healthz`
2. Check the MCP endpoint: `curl http://localhost:8080/mcp/sse`
3. Verify network connectivity
4. Check firewall settings
5. Ensure the URL is correct (no typos)

### "Tool not found" error

1. List available tools: `curl http://localhost:8080/mcp/sse | grep "tool/"`
2. Check Agent Hub logs: `docker compose logs web`
3. Verify tool registration in [`src/mcp_server.py`](src/mcp_server.py)
4. Restart both Agent Hub and Claude Code

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
  }
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
  }
}
```

### Multiple MCP Servers

You can configure multiple MCP servers in the same settings file:

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

1. **Use specific queries**: Be precise about what you're looking for
2. **Review sources**: Always check the source citations provided by Agent Hub
3. **Combine tools**: Use multiple tools together for complex tasks
4. **Iterative approach**: Start broad, then refine based on results
5. **Cache results**: For repeated queries, consider caching the results locally

## Performance Optimization

- **Pre-build index**: Run `python run.py --ingest` before starting Claude Code
- **Use lightweight models**: For quick lookups, use lighter models in config
- **Limit context**: Be specific in your queries to reduce LLM token usage
- **Batch operations**: When possible, batch related queries


## Security Considerations

- Agent Hub respects workspace boundaries (only reads files in `workspace/`)
- File editing tools (`edit_file`) require explicit confirmation in stdio mode
- MCP tools are scoped to the configured workspace
- No telemetry by default (opt-in in Phase 5)

---

**See Also:**
- [Cline Integration Guide](cline.md)
- [Continue.dev Integration Guide](continue.md)
- [Roo Code Integration Guide](roo-code.md)
- [Cursor Integration Guide](cursor.md)
- [MCP Tools Reference](../mcp/tools.md)
