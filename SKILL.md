---
name: dji-ent-release-monitor
description: >-
  Develop, debug, test, and publish the "DJI ENT Release Monitor" — a FastAPI
  WebUI and Cloudflare Pages site that parses DJI Release Notes PDFs and
  FlightHub 2 HTML release notes in English and Chinese.
---

# DJI ENT Release Monitor — developer skill

This folder is a **self-contained working copy** of the web project plus
everything needed to run, test, and publish it.

## What the app does

1. The browser loads `GET /` (a single static HTML file) which calls `GET /api/releases`.
2. Each configured source is either a DJI product Release Notes PDF or a
   FlightHub 2 page rendered to Markdown through Jina Reader.
3. The PDF and FH2 parsers independently extract the latest release into safe,
   structured JSON.
4. Results are returned as JSON. The frontend filters client-side by time window
   (1w / 2w / 30d / 2mo) and by product, and renders cards.
5. The backend caches each language response for 10 minutes; "Refresh now" sends
   `?force=1` to bypass the cache.

> Note the on-screen title is "DJI ENT Release Note Monitor".

## Folder map

```
dji-ent-release-monitor-skill/
├── SKILL.md                     ← you are here
├── AGENTS.md                    ← short entry pointer for Codex
├── src/                         ← THE EDITABLE SOURCE (the actual project)
│   ├── app/
│   │   ├── main.py              ← FastAPI app: routes /, /api/releases, cache, fan-out
│   │   ├── scraper.py           ← fetch product page, find+download Release Notes PDF
│   │   ├── pdf_parser.py        ← pdfplumber text -> {date, firmware[], whats_new[]}
│   │   ├── fh2_parser.py        ← Jina Markdown -> safe latest-release blocks
│   │   ├── products.json        ← list of {name, url} to monitor
│   │   ├── static/index.html    ← entire WebUI (HTML+CSS+JS in one file)
│   │   └── __init__.py
│   ├── requirements.txt         ← fastapi, uvicorn[standard], pdfplumber (pinned)
│   ├── README.md
│   └── run.bat                  ← original Windows launcher (kept for reference)
├── scripts/
│   ├── dev_run.sh               ← run locally with --reload (dev loop)
│   ├── smoke_test.sh            ← boot server, check / and /api/releases
│   ├── build_static_site.py     ← build public/ for Cloudflare Pages
│   ├── test_parser.py           ← offline PDF parser checks
│   └── test_fh2_parser.py       ← offline FH2 parser checks
└── reference/
    ├── architecture.md          ← request flow, modules, JSON contract, concurrency
    ├── scraping-and-parsing.md  ← DJI HTML/PDF assumptions + how to re-verify/fix
    ├── deploy-cloudflare-pages.md ← static Pages deployment + daily data build
    └── improvement-backlog.md   ← concrete, prioritized improvement ideas
```

## Quick start (development)

```bash
# Run with hot-reload, then open http://127.0.0.1:8000
scripts/dev_run.sh

# Verify after changes (offline parser checks + live HTTP smoke test)
scripts/smoke_test.sh
```

Both scripts create/reuse a venv at `.devvenv/` inside this folder.

## Build the static Cloudflare Pages artifact

```bash
scripts/build_static_site.py
```

This writes `public/index.html` plus daily data files under `public/data/`.
The GitHub Actions workflow in `.github/workflows/deploy-pages.yml` runs this
once per day and deploys `public/` to Cloudflare Pages. See
`reference/deploy-cloudflare-pages.md`.

## Required release workflow

Every completed change must go through the full web release flow:

1. Run the relevant parser tests and `scripts/smoke_test.sh`.
2. Build the static artifact with `scripts/build_static_site.py`.
3. Commit and push the change to GitHub.
4. Trigger and wait for the Cloudflare Pages deployment workflow.
5. Verify `https://dji-ent-release-monitor.pages.dev` shows the new behavior.

Local verification alone is not a completed delivery for this project.

## The most important thing to know

The PDF and FH2 parsers depend on **DJI's current external formats**, which DJI
changes without notice. They are deliberately defensive
(partial data + warnings instead of crashing), but when a product shows an error
or missing fields, the cause is almost always a layout change. Read
`reference/scraping-and-parsing.md` before touching the source parsers. It
documents every assumption (including DJI's real
`data-ga-label="dowload-..."` typo) and how to capture a fresh page/PDF to debug.

## Conventions

- Python 3.8+; standard library only in `scraper.py` and FH2 networking.
- Keep failures non-fatal: per-product errors go into the `errors[]` array and
  parse problems into `parse_warnings[]`; never let one product break the page.
- The WebUI is intentionally a single dependency-free HTML file. Keep it that way
  unless there's a strong reason; escape all interpolated strings (`esc()`).
- The supported deliverable is the website/Cloudflare Pages artifact. The
  legacy `packaging/` directory is not maintained.

## JSON contract (`GET /api/releases?lang=en|zh`)

```jsonc
{
  "generated_at": "2026-06-04T17:37:00",
  "today": "2026-06-04",
  "language": "zh",
  "product_order": ["DJI Matrice 400", "..."],   // configured order, for the UI
  "releases": [
    {
      "product": "DJI Dock 3",
      "url": "https://enterprise.dji.com/dock-3/downloads",
      "source_type": "pdf",
      "source_pdf": "https://.../release-notes.pdf",
      "listing_date": "2026-05-08",   // date shown on the website row (string|null)
      "listing_label": "DJI Dock 3 - Release Notes",
      "date": "2026-05-08",            // date parsed from inside the PDF (ISO|null)
      "days_ago": 27,                  // today - date (int|null)
      "firmware": [{"label": "Dock Firmware", "version": "v17.01.05.06"}],
      "whats_new": ["..."],
      "parse_warnings": ["..."]
    }
  ],
  "errors": [{"product": "...", "url": "...", "error": "..."}],
  "cached": false
}
```

FH2 entries use the same common date/language fields plus:

```jsonc
{
  "product": "FH2 公有版",
  "source_type": "fh2_html",
  "source_url": "https://fh.dji.com/...",
  "version": null,
  "content_blocks": [
    {"type": "heading", "level": 3, "text": "..."},
    {"type": "list", "items": ["..."]}
  ]
}
```

Changing this shape means updating `src/app/static/index.html` too (it reads
these exact fields).
