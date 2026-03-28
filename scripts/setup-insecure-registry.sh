#!/bin/bash
# scripts/setup-insecure-registry.sh
# Run this on BOTH:
#   1. The GitLab runner machine (so CI can push images)
#   2. The target deployment machine (so it can pull images)
#
# This tells Docker to trust your HTTP registry.
# Replace MYREPO:5000 with your actual registry address.

REGISTRY="${1:-MYREPO:5000}"

echo "=== Configuring Docker to trust insecure registry: $REGISTRY ==="

DAEMON_JSON="/etc/docker/daemon.json"

if [ -f "$DAEMON_JSON" ]; then
    echo "Existing $DAEMON_JSON found. Please add manually:"
    echo "  \"insecure-registries\": [\"$REGISTRY\"]"
    echo ""
    echo "Current content:"
    cat "$DAEMON_JSON"
else
    echo "Creating $DAEMON_JSON..."
    sudo mkdir -p /etc/docker
    echo "{
  \"insecure-registries\": [\"$REGISTRY\"]
}" | sudo tee "$DAEMON_JSON"
fi

echo ""
echo "Restarting Docker daemon..."
sudo systemctl restart docker

echo "Done. Verify with: docker info | grep -A5 'Insecure Registries'"
