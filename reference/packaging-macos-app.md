# Packaging the macOS app

The deliverable is a **self-contained, double-clickable `.app`**: copy it (or its
`.zip`) to any Mac and run — no Terminal, no pre-installed project files. First
run needs Python 3 + internet (to build the venv); after that it runs offline.

## Bundle layout

```
DJI ENT Release Monitor.app/
└── Contents/
    ├── Info.plist                       # LSUIElement agent app, CFBundleExecutable="DJI Release Monitor"
    ├── MacOS/
    │   └── DJI Release Monitor          # = packaging/launcher.sh (must match CFBundleExecutable)
    └── Resources/
        ├── AppIcon.icns
        └── payload/                     # the whole project, read-only
            ├── app/...                  # copied from src/app
            ├── requirements.txt
            └── VERSION
```

## How the launcher works (`packaging/launcher.sh`)

It is a bash script (no compiled binary). On launch:

1. **PATH fix** — Finder/launchd start apps with a minimal PATH; the script
   prepends Homebrew / python.org / miniconda / `/usr/sbin` so it can find
   `python3`, `lsof`, `nc`, etc.
2. **Already running?** If `127.0.0.1:8000` is open, it shows a control dialog
   (`Open Browser` / `Stop Server` / `Cancel`) and exits — so the same icon acts
   as a start/stop toggle. `Stop Server` kills the PID in
   `…/server.pid` (and anything on the port as a fallback).
3. **Payload sync** — compares `payload/VERSION` to
   `~/Library/Application Support/DJI ENT Release Monitor/.installed_version`.
   On first run or version change it copies `payload/app` + `requirements.txt`
   into that **writable** support dir. A user-edited `products.json` is preserved
   across version updates.
4. **Find Python** — tries Homebrew, `/usr/local`, python.org framework,
   miniconda, `$PATH` python3, and (only if Xcode CLT is installed, to avoid
   triggering the CLT GUI installer) `/usr/bin/python3`. Each candidate is
   validated as ≥ 3.8. If none is usable, a dialog offers **Install Apple Tools**
   (`xcode-select --install`) or **Get Python.org**.
5. **Build venv (first run only)** at `…/Application Support/…/venv` and
   `pip install -r requirements.txt`. Built with the *target machine's* Python →
   correct native architecture (Apple Silicon or Intel). This is why we never
   ship a prebuilt venv.
6. **Start server** detached (`nohup … uvicorn … &`), record the PID, poll until
   the port answers, then `open http://127.0.0.1:8000`.

Logs: `~/Library/Logs/DJI-Release-Monitor.log`.
Runtime/venv/PID: `~/Library/Application Support/DJI ENT Release Monitor/`.

### Why a per-user runtime instead of running from inside the bundle
- The `.app` may live in `/Applications` (not user-writable) and is subject to
  **Gatekeeper App Translocation** (unsigned quarantined apps run from a random
  read-only mount). Copying the payload out to Application Support sidesteps both,
  keeps `products.json` editable, and lets the venv use absolute, stable paths.

## Build

```bash
packaging/build_macos_app.sh [OUTPUT_DIR]   # default OUTPUT_DIR = <skill>/dist
```

Steps performed: create the bundle skeleton → copy `Info.plist` + `launcher.sh`
(named to match `CFBundleExecutable`) → copy/genenerate the icon → copy `src/`
into `Resources/payload/` and stamp `VERSION` → sync `CFBundleVersion` → zip with
`ditto`.

### The version-bump rule (important)
The runtime only re-copies the payload when `VERSION` **differs** from what it
previously installed. So after editing `src/`:

1. bump `packaging/VERSION` (e.g. `2.0.0` → `2.0.1`),
2. rebuild,
3. ship.

If you forget, machines that already ran an older build keep their stale copy.

## Test the packaged app (simulate a fresh/foreign Mac)

```bash
# 1) wipe the per-user runtime to force a clean first-run
rm -rf "$HOME/Library/Application Support/DJI ENT Release Monitor"
# 2) extract the zip somewhere with NO project files nearby and launch it
ditto -x -k "dist/DJI ENT Release Monitor.zip" /tmp/ziptest
open "/tmp/ziptest/DJI ENT Release Monitor.app"
# 3) watch it bootstrap
tail -f "$HOME/Library/Logs/DJI-Release-Monitor.log"
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/
```

## Shipping & Gatekeeper

The app is **unsigned / not notarized** (no paid Apple Developer ID). When a user
receives the zip via download/AirDrop it gets quarantined and Gatekeeper will
warn ("unidentified developer" / "cannot verify it is free of malware").
Workarounds to give the recipient:

- **Right-click the app → Open → Open** (one-time approval), or
- Terminal: `xattr -dr com.apple.quarantine "DJI ENT Release Monitor.app"`.

To remove this friction entirely you'd need to sign + notarize (see
`improvement-backlog.md`).

## Icon

`AppIcon.icns` is prebuilt and committed. To change the art, edit
`packaging/make_icon.py` (Pillow), delete `packaging/AppIcon.icns`, and rebuild —
the build script regenerates the `.icns` via `sips` + `iconutil` and re-caches it.
After replacing an icon, macOS may show the old one until you
`touch` the app and/or re-register it with `lsregister -f`.
