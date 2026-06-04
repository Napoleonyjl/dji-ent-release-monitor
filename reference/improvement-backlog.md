# Improvement backlog

Concrete, codebase-specific ideas for "next-step" work, roughly prioritized.
Each lists the touch points and the gotcha to watch.

## P0 — correctness & resilience

1. **Per-request timeout / overall budget for `/api/releases`.**
   With ~17 products, one slow host can stall the response. The thread-pool
   fan-out in `main._build_response()` has no overall deadline. Add a
   `concurrent.futures`-style timeout or wrap each `_process_product` with a hard
   cap, returning a timeout `error` entry instead of hanging.
   *Touch:* `app/main.py`. *Watch:* keep failures non-fatal.

2. **Clean up temp PDFs.** `scraper.scrape_product()` writes
   `tempfile.gettempdir()/dji_release_<hash>.pdf` and never deletes them. Either
   parse from an in-memory `io.BytesIO` (pdfplumber accepts a file-like object)
   or delete after parsing.
   *Touch:* `app/scraper.py` (+ `pdf_parser.parse_release_pdf` signature if you
   switch to bytes).

3. **`hash()` is salted per process.** The temp filename uses `abs(hash(pdf_url))`,
   which differs every run (PYTHONHASHSEED) — no caching benefit and unbounded
   temp files. Use `hashlib.sha1(pdf_url.encode()).hexdigest()[:16]`.
   *Touch:* `app/scraper.py`.

4. **Retry/backoff on transient HTTP errors.** A single `urllib` failure marks
   the whole product as errored. Add 1–2 retries with small backoff in
   `_http_get`.
   *Touch:* `app/scraper.py`.

## P1 — features users will want

5. **Persistence + "what changed since last check".** Store the last seen
   firmware versions per product (JSON/SQLite in Application Support) and badge
   genuinely *new* versions. Enables notifications.
   *Touch:* `app/main.py` (+ a small store module).

6. **Native notifications / scheduled checks.** Run a background poll (e.g. every
   N hours) and post a macOS notification when a new release appears. Could be a
   `launchd` agent installed by the app, or an asyncio background task in the
   server.
   *Touch:* `launcher.sh` / new agent plist / `app/main.py`.

7. **Edit the product list from the UI.** Add `GET/POST /api/products` and a small
   editor in `index.html` so users don't hand-edit `products.json` inside
   Application Support.
   *Touch:* `app/main.py`, `app/static/index.html`. *Watch:* validate URLs;
   persist to the writable runtime copy, not the read-only bundle.

8. **Server-side window filtering option.** Today the 30-day filter is purely
   client-side (the API returns everything). Fine for now, but if the product
   list grows, add an optional `?days=` query.

## P2 — quality & DX

9. **Tests.** `scripts/test_parser.py` covers the parser heuristics offline.
   Add: (a) scraper tests against saved HTML fixtures (no network) for
   `_find_release_notes_row` scoring; (b) a FastAPI `TestClient` test for
   `/api/releases` with `scrape_product`/`parse_release_pdf` monkeypatched.
   Introduce `pytest` + a `tests/` dir and fixtures under `tests/fixtures/`.

10. **Type-check & lint.** Code is fully type-hinted already — add `mypy` and
    `ruff` configs and a `make check` / CI step.

11. **Structured logging.** Replace the launcher's plain log + uvicorn default
    with a small logging config; add a log-rotation note (the single
    `~/Library/Logs/DJI-Release-Monitor.log` grows unbounded).

12. **Config constants.** Port (8000), cache TTL (600s), and the 30-day default
    are scattered. Centralize (env vars / a small config) so the packaged app can
    override the port if 8000 is taken.

## P3 — distribution

13. **Code signing + notarization.** Removes the Gatekeeper warning on other Macs.
    Requires a paid Apple Developer ID; sign the bundle (`codesign --deep
    --options runtime`), notarize (`notarytool`), and `stapler staple`. Document
    in `packaging/`.

14. **Fully offline / no-Python build.** Embed a relocatable interpreter
    (python-build-standalone) + pre-installed deps so the target needs neither
    Python nor internet. Cost: ~tens of MB and **architecture-specific** builds
    (separate arm64 / x86_64, or a universal2 strategy). Big change to
    `launcher.sh` (skip venv bootstrap; use the embedded interpreter).

15. **Auto-update.** Have the app check a URL for a newer `VERSION` and download a
    new payload (cheaper than re-distributing the whole .app since the runtime
    already re-syncs on version change).

## Known quirks to preserve (don't "fix" by accident)
- `data-ga-label="dowload-..."` — DJI's real misspelling; the regex depends on it.
- The PDF holds multiple historical releases newest-first; parsing intentionally
  stops at the second `Date:`/section heading so only the latest is shown.
- UI title ("DJI ENT Release Note Monitor") differs slightly from the app/bundle
  name ("DJI ENT Release Monitor"). Align them only if intended.
- `scraper.py` is stdlib-only on purpose (keeps the dependency surface tiny).
