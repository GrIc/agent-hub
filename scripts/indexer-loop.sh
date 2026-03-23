#!/bin/bash
INTERVAL=${INDEXER_INTERVAL_SECONDS:-3600}
echo "=== Agent Hub Indexer === Interval: ${INTERVAL}s"
while true; do
    echo "[$(date)] Running watch.py..."
    python watch.py 2>&1
    echo "[$(date)] Sleeping ${INTERVAL}s..."
    sleep $INTERVAL
done
