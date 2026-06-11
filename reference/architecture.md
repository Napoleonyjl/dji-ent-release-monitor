# Architecture

A deliberately small web app: one FastAPI process for local use, a static
frontend, source-specific parsers, and a Cloudflare Pages build path. No
database and no JS framework.

## Request flow

### Local FastAPI

```
Browser
  └─ GET /                         main.index()           -> static/index.html
  └─ GET /data/releases-<lang>.json main.get_release_snapshot()
         │
         └─ return app/data snapshot immediately, when present
  └─ GET /api/releases[?lang=en|zh][&force=1]   main.get_releases()
         │
         ├─ cache hit (<10 min, no force)? -> return cached JSON (cached:true)
         ├─ app/data snapshot exists? -> return saved JSON immediately
         │       and start one background refresh task for that language
         └─ _build_response()
                ├─ _load_products()                       reads app/products.json
                └─ for each source, in a thread pool:
                       _process_product(config, language)
                           ├─ PDF: scraper + pdf_parser
                           └─ FH2: Jina Reader + fh2_parser
                ├─ split into releases[] / errors[]
                ├─ replace transient failures with last-known-good rows by product_id
                ├─ sort releases by days_ago (None last)
                └─ return JSON (also stored in cache for 10 min and app/data)
```

The local app uses stale-while-revalidate behavior. Once a language has any
saved snapshot, visitor requests do not wait for DJI scraping or PDF parsing;
the UI can render the saved payload while `/api/releases` refreshes it in the
background.

### Cloudflare Pages public site

```
GitHub Actions (daily)
  └─ scripts/build_static_site.py
        ├─ _build_response("en") -> public/data/releases-en.json
        ├─ _build_response("zh") -> public/data/releases-zh.json
        ├─ seed src/app/data/releases-{en,zh}.json for local first-open
        └─ copy static/index.html -> public/index.html

Browser on pages.dev
  └─ GET /                         -> public/index.html
  └─ GET /data/releases-<lang>.json -> prebuilt release data
```

The public site does not run PDF parsing on visitor requests. "Reload data" only
reloads the static JSON; new data appears after the next scheduled deploy.

## Modules

### `app/main.py`
- Creates `app = FastAPI(title="DJI ENT Release Note Monitor")`.
- `APP_DIR = Path(__file__).parent` → all file paths (`products.json`,
  `static/`) are resolved relative to the module, **not** the CWD. This is why
  the app works regardless of where it's launched from.
- In-process cache: module-level `_cache` keyed by language (`en` / `zh`),
  `CACHE_TTL_SECONDS = 600`.
- Persistent snapshots: `app/data/releases-en.json` and
  `app/data/releases-zh.json`. They are returned immediately when present, and
  `/api/releases` starts a non-blocking refresh task instead of making the user
  wait for the full scrape.
- Every configured product has a stable `product_id`. Successful rows include
  `last_success_at` and `stale: false`; a transiently failed refresh reuses the
  previous row with `stale: true` and a recalculated `days_ago`.
- Concurrency: `_build_response()` runs each product through
  `loop.run_in_executor(None, _process_product, ...)` — i.e. the default thread
  pool — because `scraper`/`pdf_parser` are synchronous and I/O-bound. All
  products are fetched concurrently, then `asyncio.gather`-ed.
- Error policy: `_process_product` **never raises**; it returns a dict with an
  `error` key on failure. `get_releases` is the only place that builds the cache.

### `app/scraper.py`
- Pure stdlib (`urllib`). Returns a `ScrapedRelease` dataclass or raises
  `ScrapeError` (caught by `main`).
- English mode fetches the configured URL. Chinese mode rewrites it to the
  `/cn/.../downloads` page and prefers DJI's sibling Chinese PDF URL when the
  page still points at an English file.
- Downloads the PDF to a temp file keyed by `hash(pdf_url)` in
  `tempfile.gettempdir()`. (These temp PDFs are not cleaned up — see backlog.)
- See `scraping-and-parsing.md` for the HTML assumptions.

### `app/pdf_parser.py`
- Pure stdlib + `pdfplumber`. Returns a `ParsedRelease` dataclass; on trouble it
  appends to `warnings` rather than raising.
- Operates on the **first** (latest) release block in the PDF: DJI bundles
  historical releases newest-first in one PDF, so parsing stops at the next
  `Date:` line / section heading.

### `app/fh2_parser.py`
- Uses Jina Reader because the official FlightHub 2 VuePress HTML contains an
  empty application shell until JavaScript renders it.
- Parses the public and on-premises layouts independently and keeps only the
  latest dated release.
- Emits only text-based `heading`, `paragraph`, and `list` blocks. Images,
  remote HTML, and Markdown are never passed through to the frontend.
- Fetch or parse failures remain isolated to the affected entry through
  `errors[]`.

### `app/static/index.html`
- One file: markup + CSS in `:root` variables + vanilla JS.
- State object `{ windowDays, products:Set }` plus the current language;
  everything filters **client-side** from the latest release payload.
  On Pages, it loads `data/releases-en.json` / `data/releases-zh.json`; in the
  local FastAPI app it falls back to `/api/releases`.
  Changing the window or product selection does **not** re-fetch data. Changing
  language fetches the other static JSON file on Pages, or the matching
  `lang=en|zh` API payload in local FastAPI mode.
- All dynamic strings pass through `esc()` (HTML-escape) before insertion.

## Data shapes

`ScrapedRelease`: `product, pdf_path, pdf_url, listing_date, listing_label`.
`ParsedRelease`: `release_date: date|None, firmware: list[{label,version}],
whats_new: list[str], warnings: list[str]`.
FH2 releases add `source_type: "fh2_html"`, `source_url`, optional `version`,
and `content_blocks`. PDF entries explicitly use `source_type: "pdf"` while
retaining their existing fields.

## Why these choices
- **No bundled headless browser:** PDF pages use plain HTTP. FH2 pages use Jina
  Reader so scheduled static builds can consume rendered content without
  Playwright or Chromium.
- **Thread pool, not async HTTP:** keeps `scraper` dependency-free (stdlib
  `urllib`) while still fetching all products in parallel.
- **Single static file:** zero front-end toolchain; trivially bundled into the app.
