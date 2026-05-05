#!/usr/bin/env bash
# CORTEX session-start hook
CORTEX_DIR="$(git rev-parse --show-toplevel 2>/dev/null)/.cortex"
if [ -d "$CORTEX_DIR" ]; then
  echo "[cortex] State: $(cat $CORTEX_DIR/state.json 2>/dev/null | head -1)"
  INBOX=$(ls $CORTEX_DIR/inbox/ 2>/dev/null | wc -l | tr -d ' ')
  [ "$INBOX" -gt 0 ] && echo "[cortex] ⚠ $INBOX file(s) pending in inbox/"
fi
