#!/usr/bin/env python3
"""
web/server.py -- Multi-agent web UI with conversation history.

Features:
- Core agents + custom agents discovered from agents/defs/*.md (if web: yes)
- Conversation history per session
- Full context: RAG + custom DSL + peer reports
- Query logging and stats
"""

import argparse
import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

import sys
try:
    import pysqlite3
    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass

from src.config import load_config, get_model_for_agent, get_agent_temperature, build_custom_dsl_context
from src.client import ResilientClient
from src.rag.store import VectorStore
from src.agent_defs import load_agent_definition, discover_custom_agents
from src.reports import load_peer_reports

logger = logging.getLogger(__name__)

LOGS_DIR = Path("web/logs")
STATS_FILE = LOGS_DIR / "stats.json"

# Core agents always available in the web UI
CORE_WEB_AGENTS = {
    "expert":     {"emoji": "🧠", "desc": "Code Q&A -- explain how things work"},
    "documenter": {"emoji": "📐", "desc": "Architecture docs & diagrams"},
    "portfolio":  {"emoji": "📋", "desc": "Analyze notes -> requirements"},
    "specifier":  {"emoji": "📝", "desc": "Requirements -> technical specs"},
    "architect":  {"emoji": "🏗️", "desc": "Fullstack technical architecture"},
    "planner":    {"emoji": "📅", "desc": "Specs -> roadmap with tasks"},
    "presenter":  {"emoji": "🎬", "desc": "All docs -> slide deck"},
}

MAX_HISTORY = 20


def _build_web_agents() -> dict:
    """Build the full web agent list: core + custom agents with web: yes."""
    agents = dict(CORE_WEB_AGENTS)

    custom = discover_custom_agents()
    for name, definition in custom.items():
        cfg = definition.get("config", {})
        if cfg.get("web", False):
            agents[name] = {
                "emoji": cfg.get("emoji", "🤖"),
                "desc": cfg.get("description", f"Custom: {name}"),
            }

    return agents


# -- Logging ---

def init_logs():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if not STATS_FILE.exists():
        STATS_FILE.write_text(json.dumps({
            "total_queries": 0, "total_tokens_est": 0,
            "queries_by_day": {}, "errors": 0,
        }, indent=2))


def log_query(query, response, sources, duration_ms, client_ip, agent_name, error=None):
    init_logs()
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = LOGS_DIR / f"queries_{today}.jsonl"

    entry = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().isoformat(),
        "client_ip": client_ip,
        "agent": agent_name,
        "query": query,
        "response_length": len(response),
        "sources": [s.get("source", "") for s in sources],
        "duration_ms": duration_ms,
        "error": error,
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    try:
        stats = json.loads(STATS_FILE.read_text())
    except Exception:
        stats = {"total_queries": 0, "total_tokens_est": 0, "queries_by_day": {}, "errors": 0}

    stats["total_queries"] += 1
    stats["total_tokens_est"] += (len(query) + len(response)) // 3
    stats["queries_by_day"][today] = stats["queries_by_day"].get(today, 0) + 1
    if error:
        stats["errors"] = stats.get("errors", 0) + 1
    STATS_FILE.write_text(json.dumps(stats, indent=2, ensure_ascii=False))


# -- App ---

def create_app(cfg: dict) -> FastAPI:
    app = FastAPI(title="Agent Hub -- Web UI", docs_url=None, redoc_url=None)

    defaults = cfg.get("_defaults", {})
    client = ResilientClient(
        api_key=defaults["api_key"],
        base_url=defaults["api_base_url"],
        max_retries=defaults.get("retry_max_attempts", 8),
        base_delay=defaults.get("retry_base_delay", 2.0),
        max_delay=defaults.get("retry_max_delay", 120.0),
    )

    embed_model = cfg["models"].get("embed", "")
    store = VectorStore(client=client, embed_model=embed_model)

    dsl_context = build_custom_dsl_context(cfg)

    # Build the web agent list (core + custom with web: yes)
    web_agents = _build_web_agents()

    # Load all agent definitions and build configs
    agent_configs = {}
    for name in web_agents:
        definition = load_agent_definition(name)
        md_config = definition.get("config", {})

        # Model resolution: .md config > config.yaml agents section > default
        model_alias = md_config.get("model")
        if model_alias:
            model = cfg["models"].get(model_alias, model_alias)
        else:
            model = get_model_for_agent(cfg, name)

        temperature = md_config.get("temperature")
        if temperature is None:
            temperature = get_agent_temperature(cfg, name)

        system_prompt = definition["system_prompt"]
        peers = definition["peers"]

        if dsl_context:
            system_prompt += f"\n\n## Custom domain language\n{dsl_context}"

        agent_configs[name] = {
            "system_prompt": system_prompt,
            "model": model,
            "temperature": temperature,
            "peers": peers,
        }

    rag_top_k = cfg.get("rag", {}).get("rerank_top_k", 8)
    sessions: dict[str, list[dict]] = defaultdict(list)

    logger.info(f"[Web] Ready -- {len(agent_configs)} agents ({len(web_agents) - len(CORE_WEB_AGENTS)} custom), {store.count} chunks in index")

    # -- Routes ---

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return FRONTEND_HTML

    @app.get("/api/agents")
    async def list_agents():
        return {name: {"emoji": info["emoji"], "desc": info["desc"], "model": agent_configs[name]["model"]}
                for name, info in web_agents.items() if name in agent_configs}

    @app.post("/api/ask")
    async def ask(request: Request):
        body = await request.json()
        query = body.get("query", "").strip()
        agent_name = body.get("agent", "expert")
        session_id = body.get("session_id", "default")
        client_ip = request.client.host if request.client else "unknown"

        if not query:
            return JSONResponse({"error": "Empty query"}, status_code=400)
        if len(query) > 5000:
            return JSONResponse({"error": "Query too long (max 5000 chars)"}, status_code=400)
        if agent_name not in agent_configs:
            return JSONResponse({"error": f"Unknown agent: {agent_name}"}, status_code=400)

        acfg = agent_configs[agent_name]
        start = time.time()

        results = store.search_hierarchical(query, top_k=rag_top_k)

        system = acfg["system_prompt"]

        if acfg["peers"]:
            peer_context = load_peer_reports(acfg["peers"])
            if peer_context:
                system += f"\n\n{peer_context}"

        if results:
            context_parts = [
                f"--- [Source {i}: {r['source']} (score: {r['score']:.2f})] ---\n{r['text']}"
                for i, r in enumerate(results, 1)
            ]
            system += (
                "\n\n## Retrieved context (codebase)\n"
                "Use this information to answer. Cite sources if relevant.\n\n"
                + "\n\n".join(context_parts)
            )

        history_key = f"{session_id}:{agent_name}"
        history = sessions[history_key]

        messages = [{"role": "system", "content": system}]
        messages.extend(history[-MAX_HISTORY:])
        messages.append({"role": "user", "content": query})

        try:
            response = client.chat(
                messages=messages,
                model=acfg["model"],
                temperature=acfg["temperature"],
                max_tokens=4096,
            )
            duration_ms = int((time.time() - start) * 1000)

            history.append({"role": "user", "content": query})
            history.append({"role": "assistant", "content": response})
            if len(history) > MAX_HISTORY * 2:
                sessions[history_key] = history[-MAX_HISTORY:]

            log_query(query, response, results, duration_ms, client_ip, agent_name)

            return {
                "answer": response,
                "agent": agent_name,
                "sources": [{"file": r["source"], "score": round(r["score"], 3)} for r in results],
                "duration_ms": duration_ms,
                "history_length": len(sessions[history_key]),
            }
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            error_msg = f"{type(e).__name__}: {str(e)[:200]}"
            log_query(query, "", results, duration_ms, client_ip, agent_name, error=error_msg)
            return JSONResponse({"error": "LLM request failed.", "detail": error_msg}, status_code=502)

    @app.post("/api/clear")
    async def clear_history(request: Request):
        body = await request.json()
        session_id = body.get("session_id", "default")
        agent_name = body.get("agent")
        if agent_name:
            key = f"{session_id}:{agent_name}"
            sessions.pop(key, None)
            return {"cleared": key}
        else:
            keys = [k for k in sessions if k.startswith(f"{session_id}:")]
            for k in keys:
                del sessions[k]
            return {"cleared": len(keys)}

    @app.get("/api/stats")
    async def stats():
        init_logs()
        try:
            data = json.loads(STATS_FILE.read_text())
            data["index_size"] = store.count
            data["active_sessions"] = len(sessions)
            return data
        except Exception:
            return {"total_queries": 0, "index_size": store.count}

    @app.get("/api/logs")
    async def logs(date: Optional[str] = None, limit: int = 50):
        init_logs()
        target_date = date or datetime.now().strftime("%Y-%m-%d")
        log_file = LOGS_DIR / f"queries_{target_date}.jsonl"
        if not log_file.exists():
            return {"date": target_date, "queries": []}
        entries = []
        for line in log_file.read_text().strip().split("\n"):
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        entries.reverse()
        return {"date": target_date, "queries": entries[:limit]}

    return app


# -- Frontend ---

FRONTEND_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agent Hub</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f1117; color: #e0e0e0; min-height: 100vh; display: flex; flex-direction: column; }
        header { background: #1a1b26; border-bottom: 1px solid #2a2b3a; padding: 12px 24px; display: flex; justify-content: space-between; align-items: center; }
        header h1 { font-size: 18px; color: #7aa2f7; }
        #header-right { display: flex; gap: 16px; align-items: center; }
        #agent-select { padding: 6px 12px; border-radius: 8px; border: 1px solid #2a2b3a; background: #1a1b26; color: #e0e0e0; font-size: 14px; cursor: pointer; }
        #stats-bar { font-size: 13px; color: #888; display: flex; gap: 16px; }
        .stat-item span { color: #7aa2f7; font-weight: 600; }
        #agent-desc { font-size: 12px; color: #666; text-align: center; padding: 6px; background: #1a1b26; border-bottom: 1px solid #2a2b3a; }
        main { flex: 1; max-width: 900px; width: 100%; margin: 0 auto; padding: 24px; display: flex; flex-direction: column; }
        #chat { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; padding-bottom: 16px; }
        .message { padding: 14px 18px; border-radius: 12px; max-width: 85%; line-height: 1.6; white-space: pre-wrap; word-wrap: break-word; }
        .message.user { background: #1a3a5c; align-self: flex-end; border-bottom-right-radius: 4px; }
        .message.assistant { background: #1a1b26; border: 1px solid #2a2b3a; align-self: flex-start; border-bottom-left-radius: 4px; }
        .message.error { background: #3a1a1a; border: 1px solid #5a2a2a; color: #ff6b6b; }
        .message.system { background: #1a2a1a; border: 1px solid #2a3a2a; color: #7adf7a; font-size: 13px; align-self: center; }
        .sources { margin-top: 10px; padding-top: 10px; border-top: 1px solid #2a2b3a; font-size: 12px; color: #666; }
        .sources span { display: inline-block; background: #2a2b3a; padding: 2px 8px; border-radius: 4px; margin: 2px 4px 2px 0; font-family: monospace; font-size: 11px; }
        .duration { font-size: 11px; color: #555; margin-top: 6px; }
        #input-area { display: flex; gap: 10px; padding-top: 16px; border-top: 1px solid #2a2b3a; }
        #query-input { flex: 1; padding: 12px 16px; border-radius: 10px; border: 1px solid #2a2b3a; background: #1a1b26; color: #e0e0e0; font-size: 15px; outline: none; resize: none; min-height: 48px; max-height: 150px; font-family: inherit; }
        #query-input:focus { border-color: #7aa2f7; }
        #query-input::placeholder { color: #555; }
        #send-btn { padding: 12px 24px; border-radius: 10px; border: none; background: #7aa2f7; color: #0f1117; font-size: 15px; font-weight: 600; cursor: pointer; }
        #send-btn:hover { background: #5a8af7; }
        #send-btn:disabled { background: #333; color: #666; cursor: wait; }
        #clear-btn { padding: 8px 12px; border-radius: 8px; border: 1px solid #333; background: transparent; color: #888; font-size: 12px; cursor: pointer; }
        #clear-btn:hover { border-color: #ff6b6b; color: #ff6b6b; }
        .typing { color: #7aa2f7; font-style: italic; }
        code { background: #2a2b3a; padding: 1px 6px; border-radius: 4px; font-size: 13px; }
        pre { background: #1e1f2e; padding: 12px; border-radius: 8px; overflow-x: auto; margin: 8px 0; }
        pre code { background: none; padding: 0; }
        .mermaid-container { background: #1e1f2e; border-radius: 8px; padding: 16px; margin: 8px 0; overflow-x: auto; }
        .mermaid-container svg { max-width: 100%; height: auto; }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>mermaid.initialize({ startOnLoad: false, theme: 'dark', themeVariables: { darkMode: true, background: '#1e1f2e', primaryColor: '#7aa2f7', primaryTextColor: '#e0e0e0', lineColor: '#555' } });</script>
</head>
<body>
    <header>
        <h1>Agent Hub</h1>
        <div id="header-right">
            <select id="agent-select" onchange="switchAgent()"></select>
            <button id="clear-btn" onclick="clearHistory()">Clear history</button>
            <div id="stats-bar">
                <div class="stat-item">Index: <span id="stat-index">-</span></div>
                <div class="stat-item">Today: <span id="stat-today">-</span></div>
            </div>
        </div>
    </header>
    <div id="agent-desc">Loading agents...</div>
    <main>
        <div id="chat"></div>
        <div id="input-area">
            <textarea id="query-input" placeholder="Ask a question..." rows="1"></textarea>
            <button id="send-btn" onclick="sendQuery()">Ask</button>
        </div>
    </main>
    <script>
        const chat = document.getElementById('chat');
        const input = document.getElementById('query-input');
        const btn = document.getElementById('send-btn');
        const agentSelect = document.getElementById('agent-select');
        const agentDesc = document.getElementById('agent-desc');
        let currentAgent = 'expert';
        let sessionId = Math.random().toString(36).substring(7);
        let agents = {};
        input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 150) + 'px'; });
        input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendQuery(); } });
        async function loadAgents() {
            try { const res = await fetch('/api/agents'); agents = await res.json(); agentSelect.innerHTML = '';
            for (const [name, info] of Object.entries(agents)) { const opt = document.createElement('option'); opt.value = name; opt.textContent = `${info.emoji} ${name}`; agentSelect.appendChild(opt); }
            agentSelect.value = currentAgent; updateAgentDesc(); } catch (e) { console.error('Failed to load agents', e); }
        }
        function switchAgent() { const prev = currentAgent; currentAgent = agentSelect.value; updateAgentDesc(); if (prev !== currentAgent) { addSystemMessage(`Switched to ${agents[currentAgent]?.emoji || ''} ${currentAgent}`); } }
        function updateAgentDesc() { const info = agents[currentAgent]; if (info) { agentDesc.textContent = `${info.emoji} ${currentAgent} -- ${info.desc} (model: ${info.model})`; } }
        async function loadStats() { try { const res = await fetch('/api/stats'); const data = await res.json(); document.getElementById('stat-index').textContent = data.index_size || 0; const today = new Date().toISOString().split('T')[0]; document.getElementById('stat-today').textContent = (data.queries_by_day || {})[today] || 0; } catch (e) {} }
        function addMessage(role, content, sources, durationMs) {
            const div = document.createElement('div'); div.className = `message ${role}`;
            if (role === 'assistant') {
                let html = content
                    .replace(/```mermaid\n([\s\S]*?)```/g, '<div class="mermaid-container"><pre class="mermaid">$1</pre></div>')
                    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
                    .replace(/`([^`]+)`/g, '<code>$1</code>')
                    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                    .replace(/^### (.+)$/gm, '<strong>$1</strong>')
                    .replace(/^## (.+)$/gm, '<strong style="font-size:16px">$1</strong>')
                    .replace(/^# (.+)$/gm, '<strong style="font-size:18px">$1</strong>');
                div.innerHTML = html;
                if (sources && sources.length > 0) { const srcDiv = document.createElement('div'); srcDiv.className = 'sources'; srcDiv.innerHTML = 'Sources: ' + sources.map(s => `<span>${s.file} (${(s.score * 100).toFixed(0)}%)</span>`).join(''); div.appendChild(srcDiv); }
                if (durationMs) { const durDiv = document.createElement('div'); durDiv.className = 'duration'; durDiv.textContent = `${(durationMs / 1000).toFixed(1)}s`; div.appendChild(durDiv); }
            } else { div.textContent = content; }
            chat.appendChild(div); chat.scrollTop = chat.scrollHeight;
            try { mermaid.run({ nodes: div.querySelectorAll('.mermaid') }); } catch(e) {}
        }
        function addSystemMessage(text) { const div = document.createElement('div'); div.className = 'message system'; div.textContent = text; chat.appendChild(div); chat.scrollTop = chat.scrollHeight; }
        async function clearHistory() { try { await fetch('/api/clear', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: sessionId, agent: currentAgent }) }); chat.innerHTML = ''; addSystemMessage(`History cleared for ${currentAgent}`); } catch (e) {} }
        async function sendQuery() {
            const query = input.value.trim(); if (!query) return; input.value = ''; input.style.height = 'auto'; btn.disabled = true; addMessage('user', query);
            const typing = document.createElement('div'); typing.className = 'message assistant typing'; typing.textContent = 'Thinking...'; chat.appendChild(typing); chat.scrollTop = chat.scrollHeight;
            try { const res = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query, agent: currentAgent, session_id: sessionId }) }); chat.removeChild(typing);
            if (res.ok) { const data = await res.json(); addMessage('assistant', data.answer, data.sources, data.duration_ms); } else { const data = await res.json(); addMessage('error', `Error: ${data.error || 'Request failed'}`); }
            } catch (e) { chat.removeChild(typing); addMessage('error', `Network error: ${e.message}`); }
            btn.disabled = false; input.focus(); loadStats();
        }
        loadAgents(); loadStats(); addSystemMessage('Welcome! Select an agent above and ask a question.');
    </script>
</body>
</html>"""


# -- Main ---

def main():
    parser = argparse.ArgumentParser(description="Agent Hub -- Web UI")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Port")
    parser.add_argument("--config", "-c", default="config.yaml")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    for lib in ("httpx", "openai", "chromadb"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    cfg = load_config(args.config)
    defaults = cfg.get("_defaults", {})
    if not defaults.get("api_base_url") or not defaults.get("api_key"):
        print("ERROR: API_BASE_URL and API_KEY must be set in .env")
        sys.exit(1)

    init_logs()
    app = create_app(cfg)

    web_agents = _build_web_agents()
    custom_count = len(web_agents) - len(CORE_WEB_AGENTS)
    custom_str = f" + {custom_count} custom" if custom_count > 0 else ""

    print(f"\n  Agent Hub Web UI running at http://{args.host}:{args.port}")
    print(f"  Agents: {len(web_agents)} ({len(CORE_WEB_AGENTS)} core{custom_str})")
    print(f"  Stats: http://{args.host}:{args.port}/api/stats\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
