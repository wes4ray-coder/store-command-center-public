#!/usr/bin/env bash
# Store Command Center - launcher
# FastAPI app served by uvicorn on port 8787 (matches nginx proxy config)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR/app"

# Load .env if present (portable config — see .env.example)
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a; . "$SCRIPT_DIR/.env"; set +a
fi

PORT="${STORE_PORT:-8787}"
HOST="${STORE_HOST:-0.0.0.0}"

cd "$APP_DIR"

exec "$SCRIPT_DIR/venv/bin/uvicorn" \
    main:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers 1 \
    --proxy-headers
