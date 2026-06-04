---
name: dji-ent-release-monitor
description: >-
  Develop, debug, test, and repackage the "DJI ENT Release Monitor" — a small
  FastAPI WebUI that scrapes DJI enterprise product download pages, parses the
  latest Release Notes PDF with pdfplumber, and shows firmware updates from a
  configurable time window. It ships as a self-contained, double-clickable macOS
  .app. Use this skill when adding products, changing the scraper/PDF parser
  (especially when DJI changes their page layout or PDF template), editing the
  single-file WebUI, or rebuilding the macOS .app bundle + zip for distribution.
---

# DJI ENT Release Monitor — developer skill

This folder is a **self-contained working copy** of the project plus everything
needed to run, test, and repackage it. Use it to make "next-step" programming
improvements.

## What the app does

1. The browser loads `GET /` (a single static HTML file) which calls `GET /api/releases`.
2. For each product in `src/app/products.json`, the backend fetches the product's
   DJI download page over plain HTTP, finds the **Release Notes** PDF link, and
   downloads the PDF. The frontend can request `lang=en` or `lang=zh`; Chinese
   mode fetches the `/cn/.../downloads` page and prefers DJI's sibling Chinese
   Release Notes PDF (`_cn.pdf` / `_CN.pdf`) when the page still links to English.
3. `pdfplumber` extracts the `Date:` line, the firmware version table, and the
   `What's new` bullets from the **latest** release in that PDF.
4. Results are returned as JSON. The frontend filters client-side by time window
   (1w / 2w / 30d / 2mo) and by product, and renders cards.
5. The backend caches each language response for 10 minutes; "Refresh now" sends
   `?force=1` to bypass the cache.

> Note the on-screen title is "DJI ENT Release Note Monitor" and the byline is
> "Developed by DJI Enterprise EU GKAS team". The packaged macOS app is named
> "DJI ENT Release Monitor".

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
│   │   ├── products.json        ← list of {name, url} to monitor
│   │   ├── static/index.html    ← entire WebUI (HTML+CSS+JS in one file)
│   │   └── __init__.py
│   ├── requirements.txt         ← fastapi, uvicorn[standard], pdfplumber (pinned)
│   ├── README.md
│   └── run.bat                  ← original Windows launcher (kept for reference)
├── packaging/                   ← macOS .app build inputs
│   ├── launcher.sh              ← the app's Contents/MacOS executable (bootstrap+toggle)
│   ├── Info.plist               ← bundle metadata (LSUIElement agent app)
│   ├── AppIcon.icns             ← prebuilt icon
│   ├── make_icon.py             ← regenerate the icon art (needs Pillow)
│   ├── VERSION                  ← drives payload re-sync + CFBundle versions
│   └── build_macos_app.sh       ← assembles the .app + .zip into dist/
├── scripts/
│   ├── dev_run.sh               ← run locally with --reload (dev loop)
│   ├── smoke_test.sh            ← boot server, check / and /api/releases
│   ├── build_static_site.py     ← build public/ for Cloudflare Pages
│   └── test_parser.py           ← OFFLINE checks of the PDF parser heuristics
└── reference/
    ├── architecture.md          ← request flow, modules, JSON contract, concurrency
    ├── scraping-and-parsing.md  ← DJI HTML/PDF assumptions + how to re-verify/fix
    ├── packaging-macos-app.md   ← how the .app/launcher works; Gatekeeper notes
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

```bash
packaging/build_macos_app.sh            # writes dist/DJI ENT Release Monitor.{app,zip}
```

The build copies `src/` into the app's `Contents/Resources/payload/`. At runtime
the launcher copies that payload into `~/Library/Application Support/DJI ENT
Release Monitor/` and builds a venv there using the **target machine's** Python.
So: edit `src/`, bump `packaging/VERSION`, rebuild. See
`reference/packaging-macos-app.md` for the full lifecycle and the version-bump
rule (the runtime only re-syncs payload when `VERSION` changes).

## Build the static Cloudflare Pages artifact

```bash
scripts/build_static_site.py
```

This writes `public/index.html` plus daily data files under `public/data/`.
The GitHub Actions workflow in `.github/workflows/deploy-pages.yml` runs this
once per day and deploys `public/` to Cloudflare Pages. See
`reference/deploy-cloudflare-pages.md`.

## The most important thing to know

The scraper and PDF parser depend on **DJI's current HTML structure and PDF
template**, which DJI changes without notice. They are deliberately defensive
(partial data + warnings instead of crashing), but when a product shows an error
or missing fields, the cause is almost always a layout change. Read
`reference/scraping-and-parsing.md` before touching `scraper.py` /
`pdf_parser.py` — it documents every assumption (including DJI's real
`data-ga-label="dowload-..."` typo) and how to capture a fresh page/PDF to debug.

## Conventions

- Python 3.8+; standard library only in `scraper.py` (uses `urllib`, no `requests`).
- Keep failures non-fatal: per-product errors go into the `errors[]` array and
  parse problems into `parse_warnings[]`; never let one product break the page.
- The WebUI is intentionally a single dependency-free HTML file. Keep it that way
  unless there's a strong reason; escape all interpolated strings (`esc()`).
- Don't commit a `.venv` into `src/` or the app bundle; venvs are built per machine.

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

Changing this shape means updating `src/app/static/index.html` too (it reads
these exact fields).
