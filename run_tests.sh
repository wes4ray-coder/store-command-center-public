#!/usr/bin/env bash
# Store test suite. Runs against a THROWAWAY data dir (see tests/conftest.py) — never
# touches the live store.db. Usage: ./run_tests.sh  [extra pytest args]
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/venv/bin/python" -m pytest "$DIR/tests" -q "$@"
