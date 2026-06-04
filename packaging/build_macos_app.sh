#!/bin/bash
#
# build_macos_app.sh — assemble the self-contained "DJI ENT Release Monitor.app"
# (and a transferable .zip) from src/ + packaging/.
#
# The produced .app contains the whole project under
#   Contents/Resources/payload/
# and a launcher that, on first run, copies the payload into a writable per-user
# location (~/Library/Application Support/<app>) and builds a Python venv there.
# Nothing outside the .app is needed at runtime.
#
# Usage:
#   packaging/build_macos_app.sh [OUTPUT_DIR]
#
# OUTPUT_DIR defaults to <skill>/dist. The .app and .zip are written there.
#
# Requirements to BUILD: macOS (sips, iconutil, ditto, PlistBuddy). Pillow is
# only needed if AppIcon.icns is missing and must be regenerated.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"          # .../packaging
ROOT="$(cd "$HERE/.." && pwd)"                 # skill root
SRC="$ROOT/src"
OUT="${1:-$ROOT/dist}"

APP_NAME="DJI ENT Release Monitor"
PLIST="$HERE/Info.plist"
PB=/usr/libexec/PlistBuddy

# The on-disk executable name MUST match CFBundleExecutable in Info.plist.
EXE_NAME="$($PB -c 'Print :CFBundleExecutable' "$PLIST")"
VERSION="$(cat "$HERE/VERSION" 2>/dev/null || echo '1.0.0')"

APP_DIR="$OUT/$APP_NAME.app"
CONTENTS="$APP_DIR/Contents"

echo ">> Building '$APP_NAME.app' v$VERSION"
echo "   src   = $SRC"
echo "   out   = $OUT"

[ -f "$SRC/app/main.py" ] || { echo "ERROR: $SRC/app/main.py missing"; exit 1; }

rm -rf "$APP_DIR"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources/payload"

# --- Info.plist + launcher ---
cp -f "$PLIST" "$CONTENTS/Info.plist"
cp -f "$HERE/launcher.sh" "$CONTENTS/MacOS/$EXE_NAME"
chmod +x "$CONTENTS/MacOS/$EXE_NAME"

# --- Icon: reuse prebuilt .icns, or regenerate from make_icon.py (needs Pillow) ---
if [ -f "$HERE/AppIcon.icns" ]; then
    cp -f "$HERE/AppIcon.icns" "$CONTENTS/Resources/AppIcon.icns"
else
    echo ">> No AppIcon.icns; regenerating from make_icon.py (requires Pillow)…"
    PNG="$(mktemp -t djiicon).png"
    ICONSET="$(mktemp -d -t djiiconset)/AppIcon.iconset"; mkdir -p "$ICONSET"
    python3 "$HERE/make_icon.py" "$PNG"
    sips -z 16 16   "$PNG" --out "$ICONSET/icon_16x16.png"      >/dev/null
    sips -z 32 32   "$PNG" --out "$ICONSET/icon_16x16@2x.png"   >/dev/null
    sips -z 32 32   "$PNG" --out "$ICONSET/icon_32x32.png"      >/dev/null
    sips -z 64 64   "$PNG" --out "$ICONSET/icon_32x32@2x.png"   >/dev/null
    sips -z 128 128 "$PNG" --out "$ICONSET/icon_128x128.png"    >/dev/null
    sips -z 256 256 "$PNG" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
    sips -z 256 256 "$PNG" --out "$ICONSET/icon_256x256.png"    >/dev/null
    sips -z 512 512 "$PNG" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
    sips -z 512 512 "$PNG" --out "$ICONSET/icon_512x512.png"    >/dev/null
    cp "$PNG" "$ICONSET/icon_512x512@2x.png"
    iconutil -c icns "$ICONSET" -o "$CONTENTS/Resources/AppIcon.icns"
    cp -f "$CONTENTS/Resources/AppIcon.icns" "$HERE/AppIcon.icns"   # cache for next time
fi

# --- Payload: the whole project, bundled read-only inside the app ---
rsync -a --exclude='__pycache__' --exclude='.DS_Store' --exclude='.venv' \
      "$SRC/app" "$CONTENTS/Resources/payload/"
cp -f "$SRC/requirements.txt" "$CONTENTS/Resources/payload/requirements.txt"
[ -f "$SRC/README.md" ] && cp -f "$SRC/README.md" "$CONTENTS/Resources/payload/README.md"
echo "$VERSION" > "$CONTENTS/Resources/payload/VERSION"

# --- Keep CFBundle versions in sync with VERSION ---
$PB -c "Set :CFBundleVersion $VERSION" "$CONTENTS/Info.plist" 2>/dev/null || true
$PB -c "Set :CFBundleShortVersionString $VERSION" "$CONTENTS/Info.plist" 2>/dev/null || true

# --- Zip (ditto preserves the bundle + exec bits; correct for .app) ---
( cd "$OUT" && rm -f "$APP_NAME.zip" && ditto -c -k --sequesterRsrc --keepParent "$APP_NAME.app" "$APP_NAME.zip" )

echo ">> Done."
echo "   App: $APP_DIR"
echo "   Zip: $OUT/$APP_NAME.zip"
du -sh "$APP_DIR" "$OUT/$APP_NAME.zip" 2>/dev/null || true
