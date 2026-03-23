#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

case "${1:-help}" in
  setup)
    echo "=== Agent Hub -- Initial Setup ==="
    command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not found."; exit 1; }
    if [ ! -f .env ]; then cp .env.example .env; echo "Edit .env with your API credentials: nano .env"; exit 1; fi
    mkdir -p context/{docs,architecture,code-samples} agents/defs
    source .env 2>/dev/null
    WS="${HOST_WORKSPACE_PATH:-./workspace}"
    [ -d "$WS" ] && echo "Workspace: $WS ($(find "$WS" -type f | wc -l) files)" || echo "WARNING: Workspace '$WS' not found."
    docker compose up -d
    echo "Web UI: http://$(hostname):${WEB_PORT:-8080}"
    ;;
  update) docker compose pull && docker compose up -d && docker compose ps ;;
  status) docker compose ps; curl -s http://localhost:${WEB_PORT:-8080}/api/stats 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "Web not responding" ;;
  logs) docker compose logs -f "${2:-web}" ;;
  restart) docker compose restart && docker compose ps ;;
  stop) docker compose down ;;
  reset-index) docker compose stop indexer; rm -rf .vectordb; docker compose up -d; echo "Index cleared." ;;
  *) echo "Usage: $0 {setup|update|status|logs|restart|stop|reset-index}" ;;
esac
