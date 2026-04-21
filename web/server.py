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
import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
import uvicorn

import sys
try:
    import pysqlite3
    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass

from src.config import load_config, get_model_for_agent, get_agent_temperature, build_custom_dsl_context, build_domain_context
from src.client import ResilientClient
from src.rag.store import VectorStore
from src.agent_defs import load_agent_definition, discover_custom_agents
from src.reports import load_peer_reports
from src.pipeline_loader import discover_pipelines

logger = logging.getLogger(__name__)

LOGS_DIR = Path("web/logs")
STATS_FILE = LOGS_DIR / "stats.json"

# Core agents always available in the web UI
CORE_WEB_AGENTS = {
    "expert":      {"emoji": "🧠", "desc": "Code Q&A, review & debug -- the go-to dev assistant"},
    "documenter":  {"emoji": "📐", "desc": "Architecture docs & diagrams"},
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
    rerank_model = cfg["models"].get("rerank", "")
    store = VectorStore(client=client, embed_model=embed_model, rerank_model=rerank_model)
    graph_cfg = cfg.get("graph", {})
    if graph_cfg.get("enabled", False):
        from src.rag.graph import KnowledgeGraph
        persist_dir = graph_cfg.get("persist_dir", ".graphdb")
        graph = KnowledgeGraph(persist_dir=persist_dir)
        store.graph = graph
        logger.info(f"KnowledgeGraph loaded : {graph.node_count} nodes, {graph.edge_count} edges")

    _discovered_pipelines = discover_pipelines()

    dsl_context = build_custom_dsl_context(cfg)
    domain_context = build_domain_context(cfg)

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
        functional_context = definition.get("functional_context", "")
        peers = definition["peers"]
        extra_params = definition.get("config", {}).get("extra_params", {})

        if dsl_context:
            system_prompt += f"\n\n## Custom domain language\n{dsl_context}"
        if domain_context:
            system_prompt += f"\n\n## Domain context\n{domain_context}"
        if functional_context:
            system_prompt += f"\n\n## Agent functional context\n{functional_context}"

        agent_configs[name] = {
            "system_prompt": system_prompt,
            "model": model,
            "temperature": temperature,
            "peers": peers,
            "extra_params": extra_params,
        }

    rag_top_k = cfg.get("rag", {}).get("rerank_top_k", 8)
    sessions: dict[str, list[dict]] = defaultdict(list)

    logger.info(f"[Web] Ready -- {len(agent_configs)} agents ({len(web_agents) - len(CORE_WEB_AGENTS)} custom), {store.count} chunks in index")

    # -- Internal helper --

    def _build_messages(query: str, agent_name: str, session_id: str) -> tuple[list[dict], list]:
        """
        Build messages list with system prompt, RAG context, peer reports, and history.
        Returns (messages, rag_results).
        """
        acfg = agent_configs[agent_name]
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

        return messages, results

    def _record_history(query: str, response: str, agent_name: str, session_id: str):
        """Append query/response to session history."""
        history_key = f"{session_id}:{agent_name}"
        history = sessions[history_key]
        history.append({"role": "user", "content": query})
        history.append({"role": "assistant", "content": response})
        if len(history) > MAX_HISTORY * 2:
            sessions[history_key] = history[-MAX_HISTORY:]

    # -- Routes ---

    @app.get("/")
    async def redirect_to_admin():
        # Redirect root to admin page (placeholder until T-005)
        return RedirectResponse(url="/admin", status_code=302)

    @app.get("/debug/chat")
    async def get_debug_chat():
        return FileResponse("web/index.html")

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

        try:
            messages, results = _build_messages(query, agent_name, session_id)
            response = client.chat(
                messages=messages,
                model=acfg["model"],
                temperature=acfg["temperature"],
                max_tokens=4096,
                **acfg.get("extra_params", {}),
            )
            duration_ms = int((time.time() - start) * 1000)

            _record_history(query, response, agent_name, session_id)
            log_query(query, response, results, duration_ms, client_ip, agent_name)

            return {
                "answer": response,
                "agent": agent_name,
                "sources": [{"file": r["source"], "score": round(r["score"], 3)} for r in results],
                "duration_ms": duration_ms,
                "history_length": len(sessions[f"{session_id}:{agent_name}"]),
            }
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            error_msg = f"{type(e).__name__}: {str(e)[:200]}"
            log_query(query, "", [], duration_ms, client_ip, agent_name, error=error_msg)
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

    # -- Changelog (Time-Travel Documentation) --

    @app.get("/api/changelog")
    async def get_changelog(limit: int = 30):
        """List changelog entries (most recent first)."""
        from pathlib import Path
        changelog_dir = Path("context/changelog")
        if not changelog_dir.exists():
            return {"entries": []}
        entries = []
        for f in sorted(changelog_dir.glob("*.md"), reverse=True)[:limit]:
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                # Extract title from first line
                first_line = content.strip().split("\n")[0].lstrip("# ").strip()
                entries.append({
                    "date": f.stem,
                    "title": first_line,
                    "filename": f.name,
                })
            except Exception:
                pass
        return {"entries": entries}

    @app.get("/api/changelog/{date}")
    async def get_changelog_entry(date: str):
        """Get a specific changelog entry as markdown."""
        from pathlib import Path
        filepath = Path(f"context/changelog/{date}.md")
        if not filepath.exists():
            return JSONResponse({"error": "Not found"}, status_code=404)
        content = filepath.read_text(encoding="utf-8", errors="replace")
        return {"date": date, "content": content}
    
    try:
        from web.ide_routes import register_ide_routes
        register_ide_routes(app, cfg)
    except Exception as e:
        logger.warning(f"IDE routes failed: {e}")

    try:
        from src.mcp_server import mount_mcp_sse
        mount_mcp_sse(app, cfg)
    except Exception as e:
        logger.warning(f"MCP mount failed: {e}")


    # -- Documentation Hub routes --
    from web.docs_routes import register_docs_routes
    register_docs_routes(app, cfg, store)

    # -- Workspace routes (full CLI in web) --

    # -- OpenAI-compatible API endpoints --

    @app.get("/v1/models")
    async def list_openai_models():
        models = [
            {"id": name, "object": "model", "owned_by": "agent-hub", "created": 0}
            for name in agent_configs
        ]
        return {"object": "list", "data": models}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        """OpenAI-compatible chat completions endpoint."""
        body = await request.json()
        model = body.get("model", "expert")
        stream = body.get("stream", False)
        messages_raw = body.get("messages", [])

        # Resolve session_id
        session_id = (
            request.headers.get("X-Session-Id")
            or body.get("user", {}).get("id", "openwebui-default")
        )

        # Fallback to expert if model not in agent_configs
        if model not in agent_configs:
            model = "expert"

        acfg = agent_configs[model]

        # Extract last user message content (handle string or list of {type, text})
        query = ""
        for msg in reversed(messages_raw):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    query = content
                    break
                elif isinstance(content, list):
                    # Multimodal format: [{type: "text", text: "..."}, ...]
                    parts = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            parts.append(item.get("text", ""))
                    query = "\n".join(parts)
                    break

        if not query:
            return JSONResponse(
                {"error": "No user message found"}, status_code=400
            )

        chat_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

        if model.startswith("pipeline:"):
            return JSONResponse(
                {"error": "Pipeline execution has moved to agent-hub-projects repo."},
                status_code=404,
            )

        if stream:
            async def stream_generator():
                try:
                    messages, _ = _build_messages(query, model, session_id)

                    def sync_stream():
                        """Synchronous wrapper to iterate over chat_stream()."""
                        for chunk in client.chat_stream(
                            messages=messages,
                            model=acfg["model"],
                            temperature=acfg["temperature"],
                            max_tokens=4096,
                            **acfg.get("extra_params", {}),
                        ):
                            yield chunk

                    full_response = []
                    loop = asyncio.get_event_loop()
                    chunks_iter = await loop.run_in_executor(None, lambda: list(sync_stream()))

                    for chunk_text in chunks_iter:
                        full_response.append(chunk_text)
                        data = json.dumps({
                            "id": chat_id,
                            "object": "chat.completion.chunk",
                            "model": model,
                            "choices": [{
                                "index": 0,
                                "delta": {"content": chunk_text},
                                "finish_reason": None,
                            }],
                        })
                        yield f"data: {data}\n\n"

                    # Final chunk with finish_reason
                    final_data = json.dumps({
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        }],
                    })
                    yield f"data: {final_data}\n\n"
                    yield "data: [DONE]\n\n"

                    # Record history and log
                    response_text = "".join(full_response)
                    _record_history(query, response_text, model, session_id)

                except Exception as e:
                    error_data = json.dumps({
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": f"[Error: {type(e).__name__}: {e}]"},
                            "finish_reason": "stop",
                        }],
                    })
                    yield f"data: {error_data}\n\n"
                    yield "data: [DONE]\n\n"

            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream",
                headers={"X-Accel-Buffering": "no"},
            )
        else:
            # Non-streaming
            try:
                messages, results = _build_messages(query, model, session_id)
                response = client.chat(
                    messages=messages,
                    model=acfg["model"],
                    temperature=acfg["temperature"],
                    max_tokens=4096,
                    **acfg.get("extra_params", {}),
                )
                _record_history(query, response, model, session_id)

                return {
                    "id": chat_id,
                    "object": "chat.completion",
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": response},
                        "finish_reason": "stop",
                    }],
                }
            except Exception as e:
                return JSONResponse(
                    {"error": f"LLM request failed: {type(e).__name__}: {str(e)[:200]}"},
                    status_code=502,
                )

    return app


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
