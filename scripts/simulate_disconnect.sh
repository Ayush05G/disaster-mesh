#!/usr/bin/env bash
# Thin wrapper so CLAUDE.md's documented command
# (`bash scripts/simulate_disconnect.sh`) works — the actual orchestration
# lives in simulate_disconnect.py (process management is much less painful
# in Python than bash, and it shares harness_lib.py with Phase 3's harness).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$REPO_ROOT/.venv/Scripts/python.exe"

if [ ! -f "$PYTHON" ]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
fi

exec "$PYTHON" "$REPO_ROOT/scripts/simulate_disconnect.py"
