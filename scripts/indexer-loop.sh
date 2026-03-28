#!/bin/bash
# Agent Hub Indexer — Incremental change detection, doc generation, synthesis, and RAG update.
#
# Pipeline:
#   1. watch.py     — detect changed files, generate codex docs, update RAG for changed files
#   2. synthesize   — rebuild the doc pyramid (only missing/outdated files)
#   3. re-ingest    — full re-index of context/ + workspace/ + reports/ into vector store

INTERVAL=${INDEXER_INTERVAL_SECONDS:-3600}
echo "=== Agent Hub Indexer === Interval: ${INTERVAL}s"

while true; do
    echo ""
    echo "[$(date)] ====== Starting indexer cycle ======"

    # Step 1: Detect changes and generate per-file docs
    echo "[$(date)] Step 1/3: Running watch.py (change detection + codex docs)..."
    python watch.py 2>&1

    # Step 2: Run synthesis on updated docs (only rebuilds what's needed)
    echo "[$(date)] Step 2/3: Running synthesize.py (doc pyramid)..."
    python synthesize.py --min-level 0 2>&1

    # Step 3: Re-index everything into the vector store
    echo "[$(date)] Step 3/3: Re-indexing into RAG..."
    python run.py --ingest 2>&1

    echo "[$(date)] ====== Indexer cycle complete ======"
    echo "[$(date)] Sleeping ${INTERVAL}s..."
    sleep $INTERVAL
done