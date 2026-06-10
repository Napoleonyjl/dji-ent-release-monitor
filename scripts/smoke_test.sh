#!/bin/bash
#
# smoke_test.sh — boot the server in the dev venv and verify the HTTP surface.
#
#   * GET /              -> expects 200 + the HTML title
#   * GET /api/releases  -> expects 200 + JSON with the expected top-level keys
#     (this does LIVE scraping of DJI pages, so it needs internet and may take
#      30-60s; a network failure is reported as a WARNING, not a hard failure)
#
# Usage: scripts/smoke_test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
SRC="$ROOT/src"
VENV="$ROOT/.devvenv"
PORT=8077   # uncommon port to avoid clashing with a running app instance

PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "python3 not found"; exit 1; }

if [ ! -x "$VENV/bin/python" ]; then
    echo ">> Creating dev venv…"
    "$PY" -m venv "$VENV"
    "$VENV/bin/python" -m pip install --upgrade pip >/dev/null
    "$VENV/bin/python" -m pip install -r "$SRC/requirements.txt"
fi

echo ">> Offline parser checks"
"$VENV/bin/python" "$HERE/test_parser.py" || { echo "parser tests failed"; exit 1; }
"$VENV/bin/python" "$HERE/test_fh2_parser.py" || { echo "FH2 parser tests failed"; exit 1; }

echo ">> Booting server on :$PORT"
( cd "$SRC" && exec "$VENV/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" ) &
SVID=$!
cleanup() { kill "$SVID" 2>/dev/null; }
trap cleanup EXIT

# Wait for readiness
for _ in $(seq 1 40); do
    curl -fsS -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null && break
    sleep 0.5
done

rc=0
code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/")"
if [ "$code" = "200" ]; then echo "  ok   GET /            -> 200"; else echo "  FAIL GET / -> $code"; rc=1; fi

title="$(curl -s "http://127.0.0.1:$PORT/" | grep -o '<title>[^<]*</title>' | head -1)"
[ -n "$title" ] && echo "  ok   homepage title    -> $title" || { echo "  FAIL no <title>"; rc=1; }

echo ">> GET /api/releases (live scrape; up to 90s)…"
api="$(curl -s --max-time 90 "http://127.0.0.1:$PORT/api/releases")"
if echo "$api" | "$VENV/bin/python" -c 'import sys,json; d=json.load(sys.stdin); assert "releases" in d and "errors" in d and "product_order" in d; print("  ok   /api/releases    -> keys present; releases=%d errors=%d" % (len(d["releases"]), len(d["errors"])))' 2>/dev/null; then
    :
else
    echo "  WARN /api/releases did not return valid JSON (offline or DJI layout changed?)"
fi

echo
[ "$rc" = 0 ] && echo "SMOKE TEST PASSED" || echo "SMOKE TEST FAILED"
exit $rc
