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
    --proxy-headers \
    --forwarded-allow-ips "127.0.0.1"
    # SECURITY: --forwarded-allow-ips MUST stay narrow. It's the list of peers uvicorn
    # trusts to set X-Forwarded-* (which rewrites request.client.host). The auth guard's
    # localhost bypass keys on request.client.host==127.0.0.1, so if this is EVER widened
    # to "*", any external client could send `X-Forwarded-For: 127.0.0.1` and be treated
    # as localhost → full auth bypass. NEVER set FORWARDED_ALLOW_IPS=* / this flag to "*".
