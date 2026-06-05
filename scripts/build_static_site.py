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
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PUBLIC = ROOT / "public"
DATA_DIR = PUBLIC / "data"
APP_DATA_DIR = SRC / "app" / "data"

sys.path.insert(0, str(SRC))

from app.main import _build_response  # noqa: E402


async def build_language(language: str) -> dict:
    data = await _build_response(language)
    data["cached"] = False
    data["static"] = True
    return data


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
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Keep CDN/browser revalidation cheap. Pages will serve the JSON as static
    # assets, so daily rebuilds publish a new file body at the same URL.
    (PUBLIC / "_headers").write_text(
        "/data/*.json\n"
        "  Cache-Control: public, max-age=300, must-revalidate\n"
        "/*\n"
        "  X-Content-Type-Options: nosniff\n",
        encoding="utf-8",
    )

    snapshots: dict[str, dict] = {}
    for language in ("en", "zh"):
        print(f">> Building {language} release data")
        data = await build_language(language)
        snapshots[language] = data
        out = DATA_DIR / f"releases-{language}.json"
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        out.write_text(payload, encoding="utf-8")
        (APP_DATA_DIR / out.name).write_text(payload, encoding="utf-8")
        print(
            "   wrote %s releases=%d errors=%d"
            % (out, len(data.get("releases", [])), len(data.get("errors", [])))
        )

    _write_index_with_embedded_snapshots(snapshots)
    print("   wrote %s with embedded fallback data" % (PUBLIC / "index.html"))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
