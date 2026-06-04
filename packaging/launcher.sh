#!/bin/bash
#
# DJI ENT Release Monitor — self-contained macOS launcher
#
# The whole project is bundled inside this .app (Contents/Resources/payload).
# On first launch it copies the project into a per-user, writable location and
# builds an isolated Python virtual environment there, then starts the server
# and opens the browser. Re-launching while running shows an Open/Stop menu.
#
# Nothing outside the .app is required — copy the .app to any Mac and run it.
# (First run needs Python 3 and an internet connection to install deps.)

export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/Current/bin:/opt/miniconda3/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

PORT=8000
URL="http://127.0.0.1:${PORT}"
TITLE="DJI ENT Release Monitor"

# ---- Locations -------------------------------------------------------------
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"            # <bundle>/Contents/MacOS
RES_DIR="$(cd "$SELF_DIR/../Resources" && pwd)"      # <bundle>/Contents/Resources
PAYLOAD="$RES_DIR/payload"                           # bundled source

SUPPORT="$HOME/Library/Application Support/$TITLE"   # writable runtime
VENV="$SUPPORT/venv"
PID_FILE="$SUPPORT/server.pid"

LOG_DIR="$HOME/Library/Logs"
LOG="$LOG_DIR/DJI-Release-Monitor.log"
mkdir -p "$LOG_DIR" "$SUPPORT"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

notify() {
    /usr/bin/osascript -e "display notification \"$1\" with title \"$TITLE\"" >/dev/null 2>&1
}

die() {
    log "FATAL: $1"
    /usr/bin/osascript -e "display dialog \"$TITLE could not start:

$1

Log: $LOG\" buttons {\"OK\"} default button \"OK\" with icon stop with title \"$TITLE\"" >/dev/null 2>&1
    exit 1
}

dialog() {  # dialog "msg" '"A","B","C"' "DefaultBtn" -> prints chosen button
    /usr/bin/osascript <<OSA 2>/dev/null
set r to display dialog "$1" buttons {$2} default button "$3" with title "$TITLE" with icon note
return button returned of r
OSA
}

log "----- launch -----"
[ -f "$PAYLOAD/app/main.py" ] || die "Bundled project payload is missing. The app may be damaged; re-copy it."

# ---- Port helper (uses any available python; falls back to nc) --------------
is_up() {
    local py="$VENV/bin/python"
    [ -x "$py" ] || py="$(command -v python3 2>/dev/null)"
    [ -x "$py" ] || py="$(command -v python 2>/dev/null)"
    if [ -n "$py" ] && [ -x "$py" ]; then
        "$py" - "$PORT" <<'PY' 2>/dev/null && return 0 || return 1
import socket, sys
s = socket.socket(); s.settimeout(0.4)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
    fi
    /usr/bin/nc -z 127.0.0.1 "$PORT" >/dev/null 2>&1
}

stop_server() {
    local killed=0 pid
    if [ -f "$PID_FILE" ]; then
        pid="$(cat "$PID_FILE" 2>/dev/null)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null && killed=1; fi
        rm -f "$PID_FILE"
    fi
    local ppid; ppid="$(lsof -ti tcp:"$PORT" 2>/dev/null)"
    if [ -n "$ppid" ]; then
        kill $ppid 2>/dev/null && killed=1; sleep 1
        ppid="$(lsof -ti tcp:"$PORT" 2>/dev/null)"; [ -n "$ppid" ] && kill -9 $ppid 2>/dev/null
    fi
    log "stop_server killed=$killed"
}

# ---- Already running? Act as a control panel -------------------------------
if is_up; then
    log "already running"
    choice="$(dialog "The server is already running at $URL" '"Open Browser","Stop Server","Cancel"' "Open Browser")"
    log "choice=$choice"
    case "$choice" in
        "Open Browser") open "$URL" ;;
        "Stop Server")  stop_server; notify "Server stopped." ;;
    esac
    exit 0
fi

# ---- Sync bundled payload -> writable runtime (first run / version change) --
PV="$(cat "$PAYLOAD/VERSION" 2>/dev/null || echo 0)"
IV="$(cat "$SUPPORT/.installed_version" 2>/dev/null || echo '')"
if [ ! -f "$SUPPORT/app/main.py" ] || [ "$PV" != "$IV" ]; then
    log "syncing payload v$PV (was '${IV:-none}')"
    # Preserve a user-edited products.json across updates.
    [ -f "$SUPPORT/app/products.json" ] && cp -f "$SUPPORT/app/products.json" "$SUPPORT/.products.user.json" 2>/dev/null
    rm -rf "$SUPPORT/app"
    cp -R "$PAYLOAD/app" "$SUPPORT/app" || die "Failed to install project files into $SUPPORT"
    cp -f "$PAYLOAD/requirements.txt" "$SUPPORT/requirements.txt"
    [ -f "$SUPPORT/.products.user.json" ] && cp -f "$SUPPORT/.products.user.json" "$SUPPORT/app/products.json"
    echo "$PV" > "$SUPPORT/.installed_version"
fi
cd "$SUPPORT" || die "Cannot open runtime folder: $SUPPORT"

# ---- Find a usable Python 3 for bootstrapping the venv ---------------------
find_python() {
    local c list=(
        /opt/homebrew/bin/python3
        /usr/local/bin/python3
        /Library/Frameworks/Python.framework/Versions/Current/bin/python3
        /opt/miniconda3/bin/python3
        "$(command -v python3 2>/dev/null)"
    )
    # Only trust /usr/bin/python3 if the Command Line Tools are installed,
    # otherwise calling it would pop the CLT installer and hang.
    if /usr/bin/xcode-select -p >/dev/null 2>&1; then list+=(/usr/bin/python3); fi
    for c in "${list[@]}"; do
        [ -n "$c" ] && [ -x "$c" ] || continue
        if "$c" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,8) else 1)' >/dev/null 2>&1; then
            echo "$c"; return 0
        fi
    done
    return 1
}

python_missing() {
    local r
    r="$(/usr/bin/osascript <<OSA 2>/dev/null
set r to display dialog "$TITLE needs Python 3 (3.8+), which was not found on this Mac.

Choose how to install it, then launch the app again." buttons {"Install Apple Tools","Get Python.org","Cancel"} default button "Install Apple Tools" with title "$TITLE" with icon caution
return button returned of r
OSA
)"
    case "$r" in
        "Install Apple Tools") /usr/bin/xcode-select --install >/dev/null 2>&1 ;;
        "Get Python.org") open "https://www.python.org/downloads/macos/" ;;
    esac
    exit 1
}

# ---- Build the venv on first run (per-machine, native arch) -----------------
if [ ! -x "$VENV/bin/python" ]; then
    BP="$(find_python)" || python_missing
    log "bootstrapping venv with $BP"
    notify "First run: setting up Python environment (this can take a minute)…"
    "$BP" -m venv "$VENV" >> "$LOG" 2>&1 || die "Failed to create the Python environment."
    "$VENV/bin/python" -m pip install --upgrade pip >> "$LOG" 2>&1
    "$VENV/bin/python" -m pip install -r "$SUPPORT/requirements.txt" >> "$LOG" 2>&1 \
        || die "Failed to install dependencies. The first run needs an internet connection."
fi
PYBIN="$VENV/bin/python"

# Make sure dependencies import; reinstall once if not.
if ! "$PYBIN" -c "import fastapi, uvicorn, pdfplumber" >> "$LOG" 2>&1; then
    log "deps missing, reinstalling"
    "$PYBIN" -m pip install -r "$SUPPORT/requirements.txt" >> "$LOG" 2>&1 \
        || die "Dependencies are missing and reinstall failed (need internet). See log."
fi

# ---- Start server (detached) then open the browser when ready --------------
log "starting uvicorn"
nohup "$PYBIN" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" >> "$LOG" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"
disown 2>/dev/null
log "server pid=$SERVER_PID"

for _ in $(seq 1 60); do
    if is_up; then
        open "$URL"
        notify "Server started — opening browser."
        log "ready, opened $URL"
        exit 0
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        die "The server stopped during startup. See log for details."
    fi
    sleep 0.5
done

die "Server did not become ready in time. See log for details."
