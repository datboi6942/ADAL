#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-tui}"
shift 2>/dev/null || true

case "$MODE" in
    tui)
        exec adal tui "$@"
        ;;
    api|serve)
        exec adal api --host 0.0.0.0 --port "${API_PORT:-8000}"
        ;;
    shell)
        exec /bin/bash "$@"
        ;;
    *)
        exec "$MODE" "$@"
        ;;
esac
