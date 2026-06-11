#!/usr/bin/env python3
"""Offline checks for HTTP retries, host limits, and stale-data fallback."""

from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from app import main, scraper  # noqa: E402
from scripts.build_static_site import validate_snapshots  # noqa: E402


class FakeResponse:
    def __init__(self, payload: bytes = b"ok", read_hook=None):
        self.payload = payload
        self.read_hook = read_hook

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        if self.read_hook:
            self.read_hook()
        return self.payload


failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}  {detail}")
        failures.append(name)


def reset_host_limits() -> None:
    scraper._host_semaphores.clear()


def test_retries() -> None:
    reset_host_limits()
    responses = [
        URLError(socket.timeout("timed out")),
        FakeResponse(b"success"),
    ]
    with (
        patch.object(scraper.urllib.request, "urlopen", side_effect=responses) as call,
        patch.object(scraper.time, "sleep") as sleep,
    ):
        payload = scraper._http_get("https://cdn.example/file.pdf", retries=2)
    check("timeout is retried", payload == b"success" and call.call_count == 2)
    check("retry uses backoff", sleep.call_count == 1)

    reset_host_limits()
    unavailable = HTTPError(
        "https://cdn.example/file.pdf",
        503,
        "Service Unavailable",
        {},
        None,
    )
    with (
        patch.object(
            scraper.urllib.request,
            "urlopen",
            side_effect=[unavailable, FakeResponse(b"success")],
        ) as call,
        patch.object(scraper.time, "sleep"),
    ):
        payload = scraper._http_get("https://cdn.example/file.pdf", retries=2)
    check("HTTP 503 is retried", payload == b"success" and call.call_count == 2)

    reset_host_limits()
    not_found = HTTPError(
        "https://cdn.example/missing.pdf",
        404,
        "Not Found",
        {},
        None,
    )
    with (
        patch.object(
            scraper.urllib.request,
            "urlopen",
            side_effect=not_found,
        ) as call,
        patch.object(scraper.time, "sleep") as sleep,
    ):
        try:
            scraper._http_get("https://cdn.example/missing.pdf", retries=2)
        except HTTPError:
            pass
        else:
            check("HTTP 404 is not retried", False, "request unexpectedly succeeded")
            return
    check("HTTP 404 is not retried", call.call_count == 1 and sleep.call_count == 0)


def test_host_concurrency_limit() -> None:
    reset_host_limits()
    active = 0
    maximum = 0
    lock = threading.Lock()

    def read_hook() -> None:
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.04)
        with lock:
            active -= 1

    def urlopen(*_args, **_kwargs):
        return FakeResponse(read_hook=read_hook)

    with patch.object(scraper.urllib.request, "urlopen", side_effect=urlopen):
        threads = [
            threading.Thread(
                target=scraper._http_get,
                args=(f"https://cdn.example/file-{index}.pdf",),
            )
            for index in range(6)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    check(
        "same-host concurrency is capped at two",
        maximum == scraper.MAX_REQUESTS_PER_HOST == 2,
        f"maximum={maximum}",
    )


def test_last_known_good_fallback() -> None:
    products = [
        {
            "product_id": f"product-{index}",
            "name": f"Product {index}",
            "url": f"https://example.com/product-{index}",
        }
        for index in range(4)
    ]
    previous = {
        "generated_at": "2026-06-10T04:10:00",
        "releases": [
            {
                "product_id": product["product_id"],
                "product": product["name"],
                "url": product["url"],
                "date": "2026-06-01",
                "days_ago": 9,
                "last_success_at": "2026-06-10T04:10:00",
                "stale": False,
            }
            for product in products
        ],
    }

    def failed_product(product_id, name, url, *_args):
        return {
            "product_id": product_id,
            "product": name,
            "url": url,
            "error": "<urlopen error timed out>",
        }

    with (
        patch.object(main, "_load_products", return_value=products),
        patch.object(main, "_process_product", side_effect=failed_product),
    ):
        result = asyncio.run(main._build_response("en", previous_data=previous))

    check("four failed products use historical rows", len(result["releases"]) == 4)
    check("recovered products are removed from errors", result["errors"] == [])
    check(
        "recovered products are marked stale",
        all(row["stale"] for row in result["releases"]),
    )
    check(
        "last success timestamp is preserved",
        all(
            row["last_success_at"] == "2026-06-10T04:10:00"
            for row in result["releases"]
        ),
    )

    try:
        validate_snapshots(
            {
                "en": {
                    "errors": [
                        {
                            "product_id": "new-product",
                            "product": "New Product",
                        }
                    ]
                }
            }
        )
    except RuntimeError:
        gate_failed = True
    else:
        gate_failed = False
    check("unrecoverable products abort deployment", gate_failed)


def test_product_ids() -> None:
    products = main._load_products()
    product_ids = [product.get("product_id") for product in products]
    check("every product has a stable product_id", all(product_ids))
    check("product_id values are unique", len(product_ids) == len(set(product_ids)))


def run() -> int:
    test_retries()
    test_host_concurrency_limit()
    test_last_known_good_fallback()
    test_product_ids()
    print()
    if failures:
        print(f"{len(failures)} check(s) FAILED")
        return 1
    print("All resilience checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
