"""FastAPI app: serves the WebUI and exposes /api/releases."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse

from .pdf_parser import parse_release_pdf
from .scraper import ScrapeError, scrape_product


APP_DIR = Path(__file__).parent
PRODUCTS_FILE = APP_DIR / "products.json"
STATIC_DIR = APP_DIR / "static"

CACHE_TTL_SECONDS = 10 * 60

# Simple in-process cache by language:
# {"en": {"data": dict, "expires_at": float}, "zh": {...}}
_cache: dict = {}

app = FastAPI(title="DJI ENT Release Note Monitor")


def _load_products() -> list[dict]:
    return json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))


def _process_product(name: str, url: str, language: str) -> dict:
    """Scrape + parse a single product. Returns a result dict (never raises)."""
    try:
        scraped = scrape_product(name, url, language=language)
    except ScrapeError as e:
        return {"product": name, "url": url, "error": str(e)}
    except Exception as e:
        return {"product": name, "url": url, "error": f"Unexpected scrape error: {e}"}

    try:
        parsed = parse_release_pdf(scraped.pdf_path)
    except Exception as e:
        return {
            "product": name,
            "url": url,
            "source_pdf": scraped.pdf_url,
            "error": f"PDF parse failed: {e}",
        }

    today = date.today()
    release_date = parsed.release_date
    days_ago = (today - release_date).days if release_date else None

    return {
        "product": name,
        "url": scraped.page_url,
        "source_pdf": scraped.pdf_url,
        "language": language,
        "listing_date": scraped.listing_date,
        "listing_label": scraped.listing_label,
        "date": release_date.isoformat() if release_date else None,
        "days_ago": days_ago,
        "firmware": parsed.firmware,
        "whats_new": parsed.whats_new,
        "parse_warnings": parsed.warnings,
    }


async def _build_response(language: str) -> dict:
    """Run all per-product scrapes in a thread pool."""
    products = _load_products()
    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(None, _process_product, p["name"], p["url"], language)
        for p in products
    ]
    results = await asyncio.gather(*tasks)

    releases: list[dict] = []
    errors: list[dict] = []
    for r in results:
        if "error" in r:
            errors.append(r)
        else:
            releases.append(r)

    # Sort by newest first; entries with no date go to the bottom.
    releases.sort(
        key=lambda x: x.get("days_ago") if x.get("days_ago") is not None else 10**6
    )

    # Preserve the configured product order for the product filter UI so the
    # checkboxes don't reshuffle every refresh.
    product_order = [p["name"] for p in products]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": date.today().isoformat(),
        "language": language,
        "product_order": product_order,
        "releases": releases,
        "errors": errors,
    }


@app.get("/api/releases")
async def get_releases(
    force: int = Query(0, ge=0, le=1),
    lang: str = Query("en", pattern="^(en|zh)$"),
):
    now = time.time()
    cache_entry = _cache.get(lang)
    if not force and cache_entry and cache_entry.get("expires_at", 0) > now:
        cached = dict(cache_entry["data"])
        cached["cached"] = True
        return JSONResponse(cached)

    data = await _build_response(lang)
    _cache[lang] = {"data": data, "expires_at": now + CACHE_TTL_SECONDS}

    payload = dict(data)
    payload["cached"] = False
    return JSONResponse(payload)


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")
