#!/bin/bash
#
# dev_run.sh — run the web app locally for development (macOS / Linux).
#
# Creates a throwaway venv under <skill>/.devvenv, installs requirements, and
# starts uvicorn with --reload so code edits hot-restart the server.
#
# Usage:
#   scripts/dev_run.sh [PORT]      (default port 8000)
#
# Open http://127.0.0.1:<PORT>  (Ctrl+C to stop)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
SRC="$ROOT/src"
PORT="${1:-8000}"
VENV="$ROOT/.devvenv"

PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "python3 not found"; exit 1; }

if [ ! -x "$VENV/bin/python" ]; then
    echo ">> Creating dev venv at $VENV"
    "$PY" -m venv "$VENV"
    "$VENV/bin/python" -m pip install --upgrade pip
    "$VENV/bin/python" -m pip install -r "$SRC/requirements.txt"
fi

echo ">> Serving on http://127.0.0.1:$PORT  (Ctrl+C to stop)"
cd "$SRC"
exec "$VENV/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --reload
