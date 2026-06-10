# DJI ENT Release Note Monitor

A web dashboard that reads DJI enterprise Release Notes PDFs and FlightHub 2
HTML release pages, then publishes recent English and Chinese updates across
selectable time windows.

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
run.bat
```

or:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open http://localhost:8000

## Configure products

Edit `app/products.json`:

```json
[
  { "name": "DJI Dock 3", "url": "https://enterprise.dji.com/dock-3/downloads" },
  { "name": "DJI Matrice 350 RTK", "url": "https://enterprise.dji.com/matrice-350-rtk/downloads" }
]
```

The `url` must be the official product download page (must contain a "Manuals" section with a "Release Notes" PDF).

FlightHub 2 sources use `source_type`, localized names/URLs, and an edition:

```json
{
  "name": { "en": "FH2 Public", "zh": "FH2 公有版" },
  "source_type": "fh2_html",
  "edition": "public",
  "urls": {
    "en": "https://fh.dji.com/user-manual/en/release-notes/release-notes-public.html",
    "zh": "https://fh.dji.com/user-manual/cn/release-notes/release-notes-public.html"
  }
}
```

## How it works

1. On page load the frontend first reads `GET /data/releases-<lang>.json`, so saved content can render immediately.
2. The frontend then triggers `GET /api/releases` in the background. If a saved snapshot exists, the API returns it immediately and refreshes DJI data without blocking the page.
3. PDF sources are downloaded and parsed with `pdfplumber`.
4. FlightHub 2 pages are rendered to Markdown through Jina Reader and converted
   to safe text-only heading, paragraph, and list blocks. Images are omitted.
5. Results are filtered client-side by the selected time window. Backend results are cached for 10 minutes and written to `app/data/` for the next open.

## Static website

Build the Cloudflare Pages artifact from the repository root:

```bash
scripts/build_static_site.py
```

The supported deliverable is the website. The legacy `packaging/` directory is
not part of the current release workflow.
