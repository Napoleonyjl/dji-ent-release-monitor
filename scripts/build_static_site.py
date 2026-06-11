#!/usr/bin/env python3
"""Build the static Cloudflare Pages artifact.

Outputs:
  public/index.html
  public/data/releases-en.json
  public/data/releases-zh.json
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PUBLIC = ROOT / "public"
DATA_DIR = PUBLIC / "data"
APP_DATA_DIR = SRC / "app" / "data"
LAST_GOOD_DIR = ROOT / ".cache" / "last-known-good"
LIVE_DATA_URL = (
    "https://dji-ent-release-monitor.pages.dev/data/releases-{language}.json"
)

sys.path.insert(0, str(SRC))

from app.main import _build_response, merge_previous_snapshots  # noqa: E402


async def build_language(language: str) -> dict:
    previous = load_previous_data(language)
    data = await _build_response(language, previous_data=previous)
    data["cached"] = False
    data["static"] = True
    return data


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _fetch_live_data(language: str) -> dict | None:
    url = LIVE_DATA_URL.format(language=language)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "DJI-ENT-Release-Monitor/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        print(f"   previous source unavailable: live {language}: {error}")
        return None
    return data if isinstance(data, dict) else None


def load_previous_data(language: str) -> dict:
    candidates = [
        _read_json(LAST_GOOD_DIR / f"releases-{language}.json"),
        _fetch_live_data(language),
        _read_json(APP_DATA_DIR / f"releases-{language}.json"),
    ]
    merged = merge_previous_snapshots(language, candidates)
    print(
        "   recovered historical rows=%d"
        % len(merged.get("releases", []))
    )
    return merged


def validate_snapshots(snapshots: dict[str, dict]) -> None:
    unrecoverable = {
        language: data.get("errors", [])
        for language, data in snapshots.items()
        if data.get("errors")
    }
    if not unrecoverable:
        return

    details = "; ".join(
        f"{language}: "
        + ", ".join(
            f"{error.get('product_id')} ({error.get('product')})"
            for error in errors
        )
        for language, errors in unrecoverable.items()
    )
    raise RuntimeError(
        "Static deployment aborted because products have no last-known-good "
        f"data: {details}"
    )


def _script_safe_json(data: dict) -> str:
    return (
        json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _write_index_with_embedded_snapshots(snapshots: dict[str, dict]) -> None:
    html = (SRC / "app" / "static" / "index.html").read_text(encoding="utf-8")
    embedded = (
        "  <script>\n"
        "    window.__DJI_RELEASE_SNAPSHOTS__ = "
        + _script_safe_json(snapshots)
        + ";\n"
        "  </script>\n"
    )
    marker = "  <script>\n"
    if marker not in html:
        raise RuntimeError("Cannot find frontend <script> marker for static data injection")
    PUBLIC.joinpath("index.html").write_text(
        html.replace(marker, embedded + marker, 1),
        encoding="utf-8",
    )


async def main() -> int:
    snapshots: dict[str, dict] = {}
    for language in ("en", "zh"):
        print(f">> Building {language} release data")
        data = await build_language(language)
        snapshots[language] = data

    validate_snapshots(snapshots)

    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    LAST_GOOD_DIR.mkdir(parents=True, exist_ok=True)

    # Keep CDN/browser revalidation cheap. Pages will serve the JSON as static
    # assets, so daily rebuilds publish a new file body at the same URL.
    (PUBLIC / "_headers").write_text(
        "/data/*.json\n"
        "  Cache-Control: public, max-age=300, must-revalidate\n"
        "/*\n"
        "  X-Content-Type-Options: nosniff\n",
        encoding="utf-8",
    )

    for language, data in snapshots.items():
        out = DATA_DIR / f"releases-{language}.json"
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        out.write_text(payload, encoding="utf-8")
        (APP_DATA_DIR / out.name).write_text(payload, encoding="utf-8")
        (LAST_GOOD_DIR / out.name).write_text(payload, encoding="utf-8")
        print(
            "   wrote %s releases=%d stale=%d errors=%d"
            % (
                out,
                len(data.get("releases", [])),
                sum(1 for release in data.get("releases", []) if release.get("stale")),
                len(data.get("errors", [])),
            )
        )

    _write_index_with_embedded_snapshots(snapshots)
    print("   wrote %s with embedded fallback data" % (PUBLIC / "index.html"))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
