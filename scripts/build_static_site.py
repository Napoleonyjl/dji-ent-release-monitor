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

sys.path.insert(0, str(SRC))

from app.main import _build_response  # noqa: E402


async def build_language(language: str) -> dict:
    data = await _build_response(language)
    data["cached"] = False
    data["static"] = True
    return data


async def main() -> int:
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(SRC / "app" / "static" / "index.html", PUBLIC / "index.html")

    # Keep CDN/browser revalidation cheap. Pages will serve the JSON as static
    # assets, so daily rebuilds publish a new file body at the same URL.
    (PUBLIC / "_headers").write_text(
        "/data/*.json\n"
        "  Cache-Control: public, max-age=300, must-revalidate\n"
        "/*\n"
        "  X-Content-Type-Options: nosniff\n",
        encoding="utf-8",
    )

    for language in ("en", "zh"):
        print(f">> Building {language} release data")
        data = await build_language(language)
        out = DATA_DIR / f"releases-{language}.json"
        out.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            "   wrote %s releases=%d errors=%d"
            % (out, len(data.get("releases", [])), len(data.get("errors", [])))
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
