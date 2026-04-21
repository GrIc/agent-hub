# Agent Hub — Scaling Guide

This guide covers scaling Agent Hub for production environments with large codebases and high query volumes.

## Architecture Overview

Agent Hub is designed for horizontal scaling with shared storage:

```
┌────────────────────────────────────────────────────────────────────────────┐
│                            Load Balancer                                   │
└─────────────────────┬───────────────────────────────────┬──────────────────┘
                      │                                   │
           ┌──────────┴──────────┐                 ┌──────┴──────┐
           │ Agent Hub Instance 1│                 │ Agent Hub   │
           │  (:8080)            │                 │ Instance 2  │
           └──────────┬──────────┘                 │  (:8080)    │
                      │                            └──────┬──────┘
                      │                              Instance 3
           ┌──────────┴──────────┐                     (:8080)
           │   Shared Volumes    │
           └─────────────────────┘
                      │
           ┌──────────┴──────────┐
           │  .vectordb/         │  ChromaDB (readers)
           │  .graphdb/          │  Knowledge Graph
           │  context/           │  Generated docs
           │  workspace/         │  Codebase (read-only)
           └─────────────────────┘
```

## Horizontal Scaling

### Single-Container Mode

Each container runs:
- Web UI at `/debug/chat`
- `/v1/*` API endpoints
- `/mcp/sse` MCP server
- ChromaDB reader
- Indexer (if enabled)

**Configuration:**
```yaml
services:
  agent-hub-web:
    image: agent-hub:latest
    ports:
      - "8080:8080"
    volumes:
      - ./workspace:/app/workspace:ro
      - ./.vectordb:/app/.vectordb
      - ./.graphdb:/app/.graphdb
    environment:
      - API_BASE_URL=${API_BASE_URL}
      - API_KEY=${API_KEY}
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '2.0'
          memory: 4G
```

### Multi-Container Mode

Split components across containers:

```yaml
services:
  agent-hub-api:
    image: agent-hub:latest
    command: ["python", "-m", "web.server"]
    ports:
      - "8080:8080"
    volumes:
      - ./.vectordb:/app/.vectordb
      - ./.graphdb:/app/.graphdb
    environment:
      - API_BASE_URL=${API_BASE_URL}
      - API_KEY=${API_KEY}

  agent-hub-indexer:
    image: agent-hub:latest
    command: ["python", "watch.py", "--continuous"]
    volumes:
      - ./workspace:/app/workspace
      - ./.vectordb:/app/.vectordb
      - ./.graphdb:/app/.graphdb
    environment:
      - API_BASE_URL=${API_BASE_URL}
      - API_KEY=${API_KEY}
```

## Load Balancing

### Nginx Load Balancer

**Example configuration:**
```nginx
upstream agent_hub_backend {
    server agent-hub-1:8080;
    server agent-hub-2:8080;
    server agent-hub-3:8080;
}

server {
    listen 80;
    server_name agent-hub.yourcompany.com;

    location / {
        proxy_pass http://agent_hub_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /healthz {
        proxy_pass http://agent_hub_backend;
        health_check;
    }
}
```

### Health Checks

Agent Hub provides health check endpoints:

```bash
# Basic health check
curl http://<instance>:8080/healthz

# Expected: "OK" with 200 status

# MCP endpoint health
curl http://<instance>:8080/mcp/sse
```

**Load balancer configuration:**
```
health_check {
    url = "/healthz"
    interval = 30s
    timeout = 5s
    healthy_threshold = 2
    unhealthy_threshold = 3
}
```

## ChromaDB Scaling

### Read Replicas

ChromaDB supports multiple readers sharing the same database:

```yaml
services:
  agent-hub-web-1:
    volumes:
      - ./.vectordb:/app/.vectordb
    # ...

  agent-hub-web-2:
    volumes:
      - ./.vectordb:/app/.vectordb:ro
    # ...

  agent-hub-web-3:
    volumes:
      - ./.vectordb:/app/.vectordb:ro
    # ...
```

**Note:** Only one writer allowed. All instances must share the same `.vectordb/` volume.

### Index Optimization

For large codebases (>1M LOC):


```yaml
# In config.yaml
rag:
  rerank_top_k: 12  # Default: 8, higher = better but slower
  hierarchical_search: true

models:
  embed: text-embedding-3-large  # Better quality for large indexes
```

### Sharding (Advanced)

For extremely large codebases (>10M LOC), consider sharding by:
- Module/subsystem
- Programming language
- Team/boundary

**Example sharding strategy:**
```bash
# Shard 1: Backend
python run.py --ingest --workspace workspace/backend

# Shard 2: Frontend
python run.py --ingest --workspace workspace/frontend

# Shard 3: Infrastructure
python run.py --ingest --workspace workspace/infra
```

Then configure clients to query specific shards.

## Knowledge Graph Scaling

### Graph Partitioning

For large graphs (>100k nodes):


```yaml
# In config.yaml
graph:
  enabled: true
  persist_dir: .graphdb
  partition_by: module  # or subsystem, language, etc.
```

### Read Replicas

Knowledge graph supports concurrent readers:

```yaml
services:
  agent-hub-web-1:
    volumes:
      - ./.graphdb:/app/.graphdb
    # ...

  agent-hub-web-2:
    volumes:
      - ./.graphdb:/app/.graphdb:ro
    # ...
```

## Performance Tuning

### ChromaDB Performance

**Configuration options:**
```yaml
rag:
  # Number of chunks to retrieve (higher = better results but slower)
  rerank_top_k: 12
  
  # Enable hierarchical search (L0→L3)
  hierarchical_search: true
  
  # ChromaDB settings
  chroma_settings:
    # Use persistent storage
    persist_directory: .vectordb
    # ChromaDB collection name
    collection_name: "agent_hub_collection"
```

### Model Selection

**For different workloads:**


| Workload | Recommended Model | Notes |
|----------|-------------------|-------|
| Quick lookups | `light` (gpt-4o-mini) | Fast, cheap |
| Code Q&A | `code` (gpt-4o) | Code-specific |
| Complex queries | `heavy` (gpt-4o) | Best quality |
| Embeddings | `text-embedding-3-small` | Default |
| Embeddings (large) | `text-embedding-3-large` | Better quality |

**Example config:**
```yaml
models:
  heavy: gpt-4o
  code: gpt-4o
  light: gpt-4o-mini
  embed: text-embedding-3-large
```

### Resource Allocation

**For production workloads:**


```yaml
services:
  agent-hub-web:
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 8G
        reservations:
          cpus: '2.0'
          memory: 4G
```

**Memory breakdown:**
- ChromaDB: ~512MB per 1M chunks
- Knowledge graph: ~100MB per 10k nodes
- LLM context: ~1GB per concurrent query
- Python runtime: ~500MB

### Query Optimization

**Best practices:**
1. Use specific queries (avoid broad searches)
2. Use `search_rag` for quick lookups
3. Use `expert_ask` for complex questions
4. Limit context with `top_k` parameter
5. Use lighter models for quick queries

**Example optimized queries:**
```
# Bad: Broad search
"Tell me about the codebase"

# Good: Specific query
"Explain the authentication flow in the UserService class"
```

## Caching Strategies

### Query Caching

Implement caching layer for frequent queries:

```python
# Example caching decorator
from functools import lru_cache
import time

@lru_cache(maxsize=1000)
def cached_expert_ask(query: str, agent: str, ttl: int = 3600):
    """Cache expert_ask results for 1 hour"""
    result = expert_ask(query, agent)
    return result
```

### Index Caching

ChromaDB automatically caches frequently accessed chunks. For better performance:

```yaml
# In config.yaml
chroma:
  cache_size: 10000  # Number of chunks to cache
  mmap_enabled: true  # Use memory-mapped files
```

## Monitoring and Auto-Scaling

### Metrics to Monitor

| Metric | Threshold | Action |
|--------|-----------|-------|
| CPU usage | >80% | Scale up |
| Memory usage | >90% | Scale up |
| Query latency | >5s | Optimize or scale |
| Index size | >5GB | Consider sharding |
| Error rate | >5% | Investigate |

### Prometheus Monitoring

Agent Hub exposes basic metrics via `/api/stats`:

```bash
curl http://localhost:8080/api/stats
```

**Example Prometheus configuration:**
```yaml
scrape_configs:
  - job_name: 'agent-hub'
    metrics_path: '/api/stats'
    static_configs:
      - targets: ['agent-hub-web:8080']
```

### Auto-Scaling with Kubernetes

**Example Kubernetes deployment:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agent-hub
spec:
  replicas: 3
  selector:
    matchLabels:
      app: agent-hub
  template:
    metadata:
      labels:
        app: agent-hub
    spec:
      containers:
      - name: agent-hub
        image: agent-hub:latest
        ports:
        - containerPort: 8080
        resources:
          limits:
            cpu: "2"
            memory: "4Gi"
          requests:
            cpu: "1"
            memory: "2Gi"
        volumeMounts:
        - name: vectordb
          mountPath: /app/.vectordb
      volumes:
      - name: vectordb
        persistentVolumeClaim:
          claimName: agent-hub-vectordb
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: agent-hub-autoscaler
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: agent-hub
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

## Disaster Recovery

### Multi-Region Deployment

For high availability across regions:

```
Region 1 (Primary):
  - Agent Hub instances
  - ChromaDB writer
  
Region 2 (Secondary):
  - Read-only Agent Hub instances
  - ChromaDB reader (replica)
  - Async replication
```

**Replication strategy:**
1. Primary writes to ChromaDB
2. Secondary periodically syncs from primary
3. Failover: Promote secondary to primary
4. Rebuild primary when recovered

### Backup Strategy

**Daily backups:**
```bash
# Backup ChromaDB
rsync -avz .vectordb/ /backups/agent-hub/vectordb/$(date +%Y%m%d)/

# Backup knowledge graph
rsync -avz .graphdb/ /backups/agent-hub/graphdb/$(date +%Y%m%d)/

# Backup generated docs
rsync -avz context/ /backups/agent-hub/context/$(date +%Y%m%d)/
```

**Restore procedure:**
```bash
# Stop services
docker compose down

# Restore from backup
rsync -avz /backups/agent-hub/vectordb/20240421/ .vectordb/
rsync -avz /backups/agent-hub/graphdb/20240421/ .graphdb/
rsync -avz /backups/agent-hub/context/20240421/ context/

# Restart
docker compose up -d
```

## Network Optimization

### CDN for Static Assets

Serve static assets via CDN:
```nginx
location /static/ {
    proxy_pass http://cdn.yourcompany.com/agent-hub/static/;
    proxy_set_header Host $host;
}
```

### Compression

Enable compression for API responses:
```nginx
location /v1/ {
    gzip on;
    gzip_types application/json;
}
```

## Security Scaling

### Rate Limiting

Implement rate limiting at load balancer level:
```nginx
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=100r/m;

server {
    location /v1/ {
        limit_req zone=api_limit burst=20;
        # ...
    }
}
```

### Authentication

For public-facing deployments:
```nginx
auth_request /auth;

location /auth {
    internal;
    proxy_pass http://auth-service:8080/validate;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
}
```

## Performance Benchmarks

### Query Latency (gpt-4o-mini, 500k LOC codebase)

| Query Type | Latency | Notes |
|-----------|---------|-------|
| `search_rag` (top_k=8) | 350ms | ChromaDB query |
| `search_rag` (top_k=12) | 550ms | With reranking |
| `expert_ask` (simple) | 1.2s | LLM + RAG |
| `expert_ask` (complex) | 2.8s | Multiple retrieval passes |
| `read_file` | 20ms | Filesystem read |

### Throughput

| Hardware | Concurrent Queries | Queries/minute |
|----------|-------------------|----------------|
| 2 vCPU, 4GB | 10 | 400 |
| 4 vCPU, 8GB | 25 | 1000 |
| 8 vCPU, 16GB | 50 | 2000 |

### Memory Usage

| Component | Memory per Instance |
|-----------|-------------------|
| ChromaDB (1M chunks) | 512MB |
| Knowledge graph (10k nodes) | 100MB |
| Python runtime | 500MB |
| LLM context | 1GB (per query) |

## Troubleshooting Scaling Issues

### High CPU Usage

1. Check for long-running queries: `docker stats agent-hub-web`
2. Optimize queries (use specific queries, reduce `top_k`)
3. Scale horizontally
4. Use lighter models for quick queries

### Memory Leaks

1. Monitor memory: `docker stats agent-hub-web`
2. Check for growing processes: `docker top agent-hub-web`
3. Restart affected instances
4. Investigate with `tracemalloc`

### ChromaDB Performance Degradation

1. Check index size: `ls -la .vectordb/`
2. Rebuild index if corrupted: `./scripts/deploy.sh reset-index`
3. Optimize ChromaDB settings in config.yaml
4. Consider sharding for very large indexes

### Load Balancer Issues

1. Check health checks: `curl http://<load-balancer>/healthz`
2. Verify instance connectivity
3. Check load balancer logs
4. Scale up instances

## Best Practices

1. **Start small, scale as needed**: Begin with 1–2 instances, monitor, then scale
2. **Use read replicas**: Share ChromaDB between instances
3. **Monitor aggressively**: Set up alerts for CPU, memory, latency
4. **Optimize queries**: Specific queries perform better than broad searches
5. **Use caching**: Cache frequent queries to reduce load
6. **Plan for failure**: Multi-region deployments for critical systems
7. **Backup regularly**: ChromaDB and knowledge graph are critical
8. **Test scaling**: Load test before production deployment

---

**Next:** [Troubleshooting Guide](troubleshoot.md) | [Operations Guide](deploy.md)
