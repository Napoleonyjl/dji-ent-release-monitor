"""FastAPI app: serves the WebUI and exposes /api/releases."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse

from .fh2_parser import FH2Error, scrape_fh2_release
from .pdf_parser import parse_release_pdf
from .scraper import ScrapeError, scrape_product

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent
PRODUCTS_FILE = APP_DIR / "products.json"
STATIC_DIR = APP_DIR / "static"
DATA_DIR = APP_DIR / "data"

CACHE_TTL_SECONDS = 10 * 60

# Simple in-process cache by language:
# {"en": {"data": dict, "expires_at": float}, "zh": {...}}
_cache: dict = {}
_refresh_tasks: dict[str, asyncio.Task] = {}
_refresh_locks: dict[str, asyncio.Lock] = {}

app = FastAPI(title="DJI ENT Release Note Monitor")


def _load_products() -> list[dict]:
    return json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))


def _localized_value(value, language: str):
    if isinstance(value, dict):
        return value.get(language) or value.get("en") or next(iter(value.values()))
    return value


def _product_name(product: dict, language: str) -> str:
    return str(_localized_value(product["name"], language))


def _product_url(product: dict, language: str) -> str:
    value = product.get("urls", product.get("url"))
    return str(_localized_value(value, language))


def _product_id(product: dict) -> str:
    return str(product["product_id"])


def _infer_product_id(release: dict, products: list[dict]) -> str | None:
    existing = release.get("product_id")
    if existing:
        return str(existing)

    release_name = str(release.get("product", ""))
    for product in products:
        names = product["name"]
        if isinstance(names, dict):
            candidates = {str(value) for value in names.values()}
        else:
            candidates = {str(names)}
        if release_name in candidates:
            return _product_id(product)
    return None


def merge_previous_snapshots(language: str, snapshots: list[dict | None]) -> dict:
    """Combine historical payloads into the newest successful row per product."""
    products = _load_products()
    best: dict[str, tuple[str, dict]] = {}

    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        generated_at = str(snapshot.get("generated_at", ""))
        for release in snapshot.get("releases", []):
            if not isinstance(release, dict):
                continue
            product_id = _infer_product_id(release, products)
            if not product_id:
                continue
            candidate = copy.deepcopy(release)
            candidate["product_id"] = product_id
            freshness = str(candidate.get("last_success_at") or generated_at)
            current = best.get(product_id)
            if current is None or freshness > current[0]:
                best[product_id] = (freshness, candidate)

    return {
        "language": language,
        "releases": [item[1] for item in best.values()],
    }


def _snapshot_path(language: str) -> Path:
    return DATA_DIR / f"releases-{language}.json"


def _read_snapshot(language: str) -> Optional[dict]:
    path = _snapshot_path(language)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "releases" not in data:
        return None
    return data


def _write_snapshot(language: str, data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _snapshot_path(language)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _response_payload(data: dict, *, cached: bool, stale: bool, updating: bool) -> dict:
    payload = dict(data)
    payload.pop("static", None)
    payload["cached"] = cached
    payload["stale"] = stale
    payload["updating"] = updating
    return payload


def _process_product(
    product_id: str,
    name: str,
    url: str,
    language: str,
    scrape_name: str | None = None,
    source_type: str = "pdf",
    edition: str | None = None,
) -> dict:
    """Scrape + parse a single product. Returns a result dict (never raises)."""
    if source_type == "fh2_html":
        try:
            parsed = scrape_fh2_release(url, edition or "")
        except FH2Error as e:
            return {
                "product_id": product_id,
                "product": name,
                "url": url,
                "error": str(e),
            }
        except Exception as e:
            return {
                "product_id": product_id,
                "product": name,
                "url": url,
                "error": f"Unexpected FH2 error: {e}",
            }

        today = date.today()
        release_date = parsed.release_date
        days_ago = (today - release_date).days if release_date else None
        return {
            "product_id": product_id,
            "product": name,
            "url": url,
            "source_type": "fh2_html",
            "source_url": url,
            "language": language,
            "date": release_date.isoformat() if release_date else None,
            "days_ago": days_ago,
            "version": parsed.version,
            "content_blocks": parsed.content_blocks,
            "parse_warnings": parsed.warnings,
        }

    if source_type != "pdf":
        return {
            "product_id": product_id,
            "product": name,
            "url": url,
            "error": f"Unsupported source type: {source_type}",
        }

    source_name = scrape_name or name
    try:
        scraped = scrape_product(source_name, url, language=language)
    except ScrapeError as e:
        return {
            "product_id": product_id,
            "product": name,
            "url": url,
            "error": str(e),
        }
    except Exception as e:
        return {
            "product_id": product_id,
            "product": name,
            "url": url,
            "error": f"Unexpected scrape error: {e}",
        }

    try:
        parsed = parse_release_pdf(scraped.pdf_path)
    except Exception as e:
        return {
            "product_id": product_id,
            "product": name,
            "url": url,
            "source_pdf": scraped.pdf_url,
            "error": f"PDF parse failed: {e}",
        }

    today = date.today()
    release_date = parsed.release_date
    days_ago = (today - release_date).days if release_date else None

    return {
        "product_id": product_id,
        "product": name,
        "url": scraped.page_url,
        "source_type": "pdf",
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


def _fallback_release(
    previous: dict,
    product: dict,
    language: str,
) -> dict:
    fallback = copy.deepcopy(previous)
    fallback["product_id"] = _product_id(product)
    fallback["product"] = _product_name(product, language)
    fallback["url"] = _product_url(product, language)
    fallback["language"] = language
    fallback["stale"] = True
    fallback["stale_reason"] = "source_temporarily_unavailable"

    raw_date = fallback.get("date")
    try:
        release_date = date.fromisoformat(raw_date) if raw_date else None
    except (TypeError, ValueError):
        release_date = None
    fallback["days_ago"] = (date.today() - release_date).days if release_date else None
    return fallback


async def _build_response(
    language: str,
    previous_data: dict | None = None,
) -> dict:
    """Run all per-product scrapes in a thread pool."""
    products = _load_products()
    if previous_data is None:
        previous_data = _read_snapshot(language)
    previous = merge_previous_snapshots(language, [previous_data])
    previous_by_id = {
        release["product_id"]: release
        for release in previous.get("releases", [])
        if release.get("product_id")
    }

    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(
            None,
            _process_product,
            _product_id(p),
            _product_name(p, language),
            _product_url(p, language),
            language,
            p.get("scrape_name"),
            p.get("source_type", "pdf"),
            p.get("edition"),
        )
        for p in products
    ]
    results = await asyncio.gather(*tasks)

    generated_at = datetime.now().isoformat(timespec="seconds")
    releases: list[dict] = []
    errors: list[dict] = []
    for product, result in zip(products, results):
        product_id = _product_id(product)
        r = result
        if "error" in r:
            logger.warning(
                "Product refresh failed product_id=%s language=%s error=%s",
                product_id,
                language,
                r["error"],
            )
            previous_release = previous_by_id.get(product_id)
            if previous_release:
                releases.append(_fallback_release(previous_release, product, language))
            else:
                errors.append(
                    {
                        "product_id": product_id,
                        "product": _product_name(product, language),
                        "url": _product_url(product, language),
                        "error": "Data source temporarily unavailable",
                    }
                )
        else:
            r["stale"] = False
            r["last_success_at"] = generated_at
            r.pop("stale_reason", None)
            releases.append(r)

    # Sort by newest first; entries with no date go to the bottom.
    releases.sort(
        key=lambda x: x.get("days_ago") if x.get("days_ago") is not None else 10**6
    )

    # Preserve the configured product order for the product filter UI so the
    # checkboxes don't reshuffle every refresh.
    product_order = [_product_name(p, language) for p in products]

    return {
        "generated_at": generated_at,
        "today": date.today().isoformat(),
        "language": language,
        "product_order": product_order,
        "releases": releases,
        "errors": errors,
    }


async def _refresh_language(language: str) -> None:
    lock = _refresh_locks.setdefault(language, asyncio.Lock())
    async with lock:
        data = await _build_response(language)
        _cache[language] = {
            "data": data,
            "expires_at": time.time() + CACHE_TTL_SECONDS,
        }
        _write_snapshot(language, data)


def _start_refresh(language: str) -> bool:
    task = _refresh_tasks.get(language)
    if task and not task.done():
        return False

    task = asyncio.create_task(_refresh_language(language))
    _refresh_tasks[language] = task

    def _clear(done_task: asyncio.Task) -> None:
        current = _refresh_tasks.get(language)
        if current is done_task:
            _refresh_tasks.pop(language, None)

    task.add_done_callback(_clear)
    return True


def _is_updating(language: str) -> bool:
    task = _refresh_tasks.get(language)
    return bool(task and not task.done())


@app.get("/api/releases")
async def get_releases(
    force: int = Query(0, ge=0, le=1),
    lang: str = Query("en", pattern="^(en|zh)$"),
):
    now = time.time()
    cache_entry = _cache.get(lang)
    if not force and cache_entry and cache_entry.get("expires_at", 0) > now:
        return JSONResponse(
            _response_payload(
                cache_entry["data"],
                cached=True,
                stale=False,
                updating=_is_updating(lang),
            )
        )

    snapshot = _read_snapshot(lang)
    if snapshot:
        _start_refresh(lang)
        return JSONResponse(
            _response_payload(
                snapshot,
                cached=True,
                stale=True,
                updating=True,
            )
        )

    data = await _build_response(lang)
    _cache[lang] = {"data": data, "expires_at": now + CACHE_TTL_SECONDS}
    _write_snapshot(lang, data)

    return JSONResponse(_response_payload(data, cached=False, stale=False, updating=False))


@app.get("/data/releases-{lang}.json")
async def get_release_snapshot(lang: str):
    if lang not in {"en", "zh"}:
        return JSONResponse({"error": "Unsupported language"}, status_code=404)
    snapshot = _read_snapshot(lang)
    if not snapshot:
        return JSONResponse({"error": "No release snapshot has been generated yet"}, status_code=404)
    return JSONResponse(
        _response_payload(
            snapshot,
            cached=True,
            stale=True,
            updating=_is_updating(lang),
        )
    )


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")
