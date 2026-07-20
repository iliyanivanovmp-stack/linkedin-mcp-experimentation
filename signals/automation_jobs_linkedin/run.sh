#!/usr/bin/env bash
# Run the automation jobs signal using the mcp-server-linkedin Python environment.
# Usage: ./run.sh [--reset-state]

set -e

export AUTOMATION_JOBS_SHEET_ID="1GmV-FEfYKEIODbpJanLqxlMDbjMa7DHijNJtnZZpsnk"

PYTHON=~/.local/share/uv/tools/mcp-server-linkedin/bin/python3
SCRIPT="$(dirname "$0")/track_jobs.py"

exec "$PYTHON" "$SCRIPT" "$@"
