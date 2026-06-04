# DJI ENT Release Note Monitor

A small WebUI that checks DJI enterprise product download pages, reads the latest Release Notes PDF, and shows firmware updates published in the last 30 days.

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

## How it works

1. On page load the frontend calls `GET /api/releases`.
2. The backend fetches each product's download page via HTTP, finds the Release Notes row whose label best matches the product name, and downloads the linked PDF.
3. `pdfplumber` extracts the `Date:` line, the firmware version table, and the `What's new` section.
4. Results are filtered to entries published in the last 30 days, then returned as JSON.
5. Backend caches results for 10 minutes. Click "Refresh now" in the UI to bypass the cache.
