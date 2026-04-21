# Agent Hub — Troubleshooting Guide

This guide covers common issues and their solutions when running Agent Hub.

## General Troubleshooting

### Agent Hub won't start

**Symptoms:**
- Container exits immediately
- Logs show errors
- Port 8080 already in use

**Solutions:**

1. **Check port availability:**
   ```bash
   # Windows
   netstat -ano | findstr 8080
   
   # macOS/Linux
   lsof -i :8080
   ```
   
   If port is in use, either:
   - Stop the conflicting service
   - Change Agent Hub port in `docker-compose.yml`

2. **Check logs:**
   ```bash
   docker compose logs web
   ```

3. **Verify .env configuration:**
   ```bash
   docker compose config
   ```

4. **Check disk space:**
   ```bash
   df -h
   ```

### Health check fails

**Symptoms:**
- `/healthz` returns 500 or timeout
- Services show as unhealthy

**Solutions:**

1. **Check service logs:**
   ```bash
   docker compose logs web
   ```

2. **Verify database connectivity:**
   ```bash
   docker compose exec web ls -la .vectordb/
   ```

3. **Check ChromaDB integrity:**
   ```bash
   docker compose exec web python -c "from src.rag.store import VectorStore; vs = VectorStore(); print('Index size:', vs.count)"
   ```

4. **Rebuild index if corrupted:**
   ```bash
   ./scripts/deploy.sh reset-index
   ```

## MCP Server Issues

### Tools not available

**Symptoms:**
- `list_tools` returns empty list
- MCP client reports "tool not found"

**Solutions:**

1. **Verify tool registration:**
   ```bash
   docker compose exec web python -c "from src.mcp_server import mount_mcp_sse; print('Tools registered')"
   ```

2. **Check agent definitions:**
   ```bash
   ls -la agents/defs/
   cat agents/defs/expert.md
   ```

3. **Restart services:**
   ```bash
   docker compose restart web
   ```

### MCP connection refused

**Symptoms:**
- Client reports "connection refused"
- `curl http://localhost:8080/mcp/sse` fails

**Solutions:**

1. **Verify service is running:**
   ```bash
   docker compose ps
   ```

2. **Check network connectivity:**
   ```bash
   docker compose exec web curl -v http://localhost:8080/mcp/sse
   ```

3. **Verify port mapping:**
   ```bash
   docker compose port web 8080
   ```

## Search and RAG Issues

### No results returned

**Symptoms:**
- `search_rag` returns empty results
- `expert_ask` returns "no context found"

**Solutions:**

1. **Check index status:**
   ```bash
   curl http://localhost:8080/api/stats
   ```
   
   If `index_size` is 0, index needs rebuilding.

2. **Verify codebase is indexed:**
   ```bash
   ls -la context/docs/
   ls -la .vectordb/
   ```

3. **Rebuild index:**
   ```bash
   docker compose exec web python run.py --ingest
   ```

4. **Check workspace path:**
   ```bash
   # In .env
   WORKSPACE_PATH=./workspace
   
   # Verify symlink
   ls -la workspace
   ```

### Poor search results

**Symptoms:**
- Results are irrelevant
- Low scores in citations
- Missing relevant files

**Solutions:**

1. **Check ChromaDB settings:**
   ```yaml
   # In config.yaml
   rag:
     rerank_top_k: 12  # Increase for better results
     hierarchical_search: true
   ```

2. **Verify embedding model:**
   ```yaml
   models:
     embed: text-embedding-3-small  # Or larger model
   ```

3. **Check query specificity:**
   ```
   # Bad: Broad query
   "Tell me about the codebase"
   
   # Good: Specific query
   "Explain the authentication flow in UserService"
   ```

4. **Rebuild index with better settings:**
   ```bash
   ./scripts/deploy.sh reset-index
   ```

## LLM and API Issues

### LLM API failures

**Symptoms:**
- `expert_ask` returns "LLM request failed"
- High error rate in `/api/stats`

**Solutions:**

1. **Check API credentials:**
   ```bash
   # In .env
   API_BASE_URL=https://api.openai.com/v1
   API_KEY=sk-your-key-here
   ```

2. **Verify API endpoint:**
   ```bash
   curl -H "Authorization: Bearer $API_KEY" "$API_BASE_URL/models"
   ```

3. **Check model availability:**
   ```bash
   curl -H "Authorization: Bearer $API_KEY" "$API_BASE_URL/models"
   ```

4. **Adjust timeout settings:**
   ```yaml
   # In config.yaml
   client:
     max_retries: 8
     base_delay: 2.0
     max_delay: 120.0
   ```

### Slow queries

**Symptoms:**
- Queries take >5 seconds
- High latency in `/api/stats`

**Solutions:**

1. **Use lighter models:**
   ```yaml
   # In config.yaml
   models:
     heavy: gpt-4o-mini  # Instead of gpt-4o
     light: gpt-4o-mini  # For quick lookups
   ```

2. **Reduce rerank_top_k:**
   ```yaml
   rag:
     rerank_top_k: 8  # Default is 12
   ```

3. **Use specific queries:**
   ```
   # Bad: Broad search
   "Tell me about everything"
   
   # Good: Specific query
   "Find the UserService class definition"
   ```

4. **Check ChromaDB performance:**
   ```bash
   docker compose exec web python -c "from src.rag.store import VectorStore; vs = VectorStore(); print('Index size:', vs.count)"
   ```

## File System Issues

### Workspace not accessible

**Symptoms:**
- `read_file` returns "file not found"
- `/scan` doesn't find files

**Solutions:**

1. **Check workspace path:**
   ```bash
   # In .env
   WORKSPACE_PATH=./workspace
   
   # Verify symlink
   ls -la workspace
   
   # Or copy
   cp -r /path/to/codebase workspace
   ```

2. **Check permissions:**
   ```bash
   ls -ld workspace
   chmod 755 workspace
   ```

3. **Verify file types:**
   ```bash
   # Agent Hub reads these by default
   find workspace -name "*.py" -o -name "*.js" -o -name "*.ts" -o -name "*.java" | head -20
   ```

### Generated files not created

**Symptoms:**
- `context/docs/` is empty
- `/scan` doesn't generate files

**Solutions:**

1. **Check codex agent:**
   ```bash
   docker compose exec web python run.py --agent codex --skip-ingest
   ```

2. **Verify agent definitions:**
   ```bash
   cat agents/defs/codex.md
   ```

3. **Check system prompts:**
   ```bash
   # Should include file generation instructions
   grep -A 10 "## Output" agents/defs/codex.md
   ```

## Web UI Issues

### Debug chat not working

**Symptoms:**
- `/debug/chat` shows blank page
- JavaScript errors in console
- No agents listed

**Solutions:**

1. **Check web server:**
   ```bash
   curl -v http://localhost:8080/debug/chat
   ```

2. **Verify JavaScript dependencies:**
   ```bash
   # Check if CDN resources load
   curl https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js
   curl https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/highlight.min.js
   ```

3. **Check browser console:**
   - Open `/debug/chat` in browser
   - Press F12 → Console
   - Look for 404 errors or JavaScript errors

### Admin page missing

**Symptoms:**
- `/` redirects but shows nothing
- `/admin` returns 404

**Solutions:**

1. **Check web server routes:**
   ```bash
   docker compose exec web python -c "from web.server import create_app; app = create_app({}); print(list(app.routes.keys()))" | grep -E "admin|/"
   ```

2. **Verify route registration:**
   ```python
   # In web/server.py
   @app.get("/")
   async def redirect_to_admin():
       return RedirectResponse(url="/admin", status_code=302)
   ```

3. **Check if admin page exists:**
   ```bash
   ls -la web/admin.html  # Should exist
   ```

## Docker Issues

### Container crashes on startup

**Symptoms:**
- Container exits with code 1
- Logs show Python errors

**Solutions:**

1. **Check Python dependencies:**
   ```bash
   docker compose exec web pip list
   ```

2. **Verify Python version:**
   ```bash
   docker compose exec web python --version
   ```

3. **Check missing dependencies:**
   ```bash
   docker compose logs web | grep "ModuleNotFoundError"
   ```

### Docker build fails

**Symptoms:**
- `docker compose build` fails
- Dockerfile errors

**Solutions:**

1. **Check Dockerfile:**
   ```bash
   cat Dockerfile
   ```

2. **Verify build context:**
   ```bash
   docker compose build --no-cache
   ```

3. **Check disk space:**
   ```bash
   docker system df
   ```

## Performance Issues

### High memory usage

**Symptoms:**
- Container OOM killed
- `docker stats` shows >90% memory usage

**Solutions:**

1. **Check memory usage:**
   ```bash
   docker stats agent-hub-web
   ```

2. **Reduce concurrent queries:**
   ```yaml
   # In config.yaml
   client:
     max_concurrent: 5  # Default is 10
   ```

3. **Use lighter models:**
   ```yaml
   models:
     heavy: gpt-4o-mini
     light: gpt-4o-mini
   ```

4. **Scale horizontally:**
   ```yaml
   services:
     agent-hub-web:
       deploy:
         replicas: 2
   ```

### High CPU usage

**Symptoms:**
- Container CPU >80%
- Slow queries

**Solutions:**

1. **Check CPU usage:**
   ```bash
   docker stats agent-hub-web
   ```

2. **Optimize queries:**
   ```
   # Use specific queries
   "Find UserService class" vs "Tell me about everything"
   ```

3. **Reduce rerank_top_k:**
   ```yaml
   rag:
     rerank_top_k: 8
   ```

4. **Use lighter models:**
   ```yaml
   models:
     heavy: gpt-4o-mini
   ```

## Network Issues

### Connection refused between containers

**Symptoms:**
- Containers can't communicate
- `curl` from one container to another fails

**Solutions:**

1. **Check network configuration:**
   ```bash
   docker network inspect agent-hub_default
   ```

2. **Verify service names:**
   ```yaml
   # In docker-compose.yml
   services:
     web:
       # ...
     indexer:
       depends_on:
         - web
   ```

3. **Check DNS resolution:**
   ```bash
   docker compose exec web ping indexer
   ```

### External access fails

**Symptoms:**
- Can't access `http://localhost:8080`
- Firewall blocking port

**Solutions:**

1. **Check port binding:**
   ```bash
   docker compose port web 8080
   ```

2. **Verify firewall:**
   ```bash
   # Windows
   netsh advfirewall firewall show rule name=all | findstr 8080
   
   # macOS
   sudo lsof -i :8080
   
   # Linux
   sudo ufw status
   ```

3. **Check network mode:**
   ```yaml
   # In docker-compose.yml
   services:
     web:
       ports:
         - "8080:8080"
   ```

## Logging and Debugging

### Enable debug logging

**To enable verbose logging:**
```bash
docker compose down
python -m web.server --verbose
```

Or in `docker-compose.yml`:
```yaml
services:
  web:
    command: ["python", "-m", "web.server", "--verbose"]
```

### View logs

```bash
# View all logs
docker compose logs -f

# View specific service
docker compose logs -f web

# View logs in real-time
docker compose logs -f --tail=100

# View logs for last hour
docker compose logs --since 1h
```

### Export logs

```bash
# Save logs to file
docker compose logs -t > agent-hub-logs-$(date +%Y%m%d).txt

# Search logs
grep "ERROR\|FAILED" agent-hub-logs-*.txt
```

## Common Error Messages

### "No agent named 'expert'"

**Cause:** Expert agent definition missing or not loaded

**Solution:**
```bash
ls -la agents/defs/expert.md
cat agents/defs/expert.md
```

### "ChromaDB collection not found"

**Cause:** Index not built or corrupted

**Solution:**
```bash
./scripts/deploy.sh reset-index
```

### "LLM request failed: AuthenticationError"

**Cause:** Invalid API key

**Solution:**
```bash
# Check .env
cat .env | grep API_KEY

# Test API endpoint
curl -H "Authorization: Bearer $API_KEY" "$API_BASE_URL/models"
```

### "File not found: workspace/file.py"

**Cause:** Workspace path incorrect or file missing

**Solution:**
```bash
# Check workspace
ls -la workspace/file.py

# Or recreate symlink
rm -rf workspace
ln -s /path/to/your/code workspace
```

### "MCP tool not found: expert_ask"

**Cause:** Tool not registered or MCP server not mounted

**Solution:**
```bash
# Check MCP server
docker compose exec web python -c "from src.mcp_server import mount_mcp_sse; mount_mcp_sse(None, {}); print('MCP mounted')"

# Check tool registration
docker compose exec web python -c "from src.mcp_server import TOOLS; print([t.name for t in TOOLS])"
```

## Getting Help

### Check official documentation
- [Architecture Overview](../architecture.md)
- [MCP Tools Reference](../mcp/tools.md)
- [Operations Guide](deploy.md)

### Check GitHub issues
- https://github.com/GrIc/agent-hub/issues

### Check discussions
- https://github.com/GrIc/agent-hub/discussions

### Contact maintainers
- Open a new issue with detailed logs and reproduction steps

---

**Next:** [Deployment Guide](deploy.md) | [Scaling Guide](scale.md)
