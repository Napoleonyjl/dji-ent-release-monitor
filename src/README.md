# DJI ENT Release Note Monitor

A small WebUI that checks DJI enterprise product download pages, reads the latest Release Notes PDF, and shows firmware updates across selectable time windows.

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

1. On page load the frontend first reads `GET /data/releases-<lang>.json`, so saved content can render immediately.
2. The frontend then triggers `GET /api/releases` in the background. If a saved snapshot exists, the API returns it immediately and refreshes DJI data without blocking the page.
3. The backend fetches each product's download page via HTTP, finds the Release Notes row whose label best matches the product name, and downloads the linked PDF.
4. `pdfplumber` extracts the `Date:` line, the firmware version table, and the `What's new` section.
5. Results are filtered client-side by the selected time window. Backend results are cached for 10 minutes and written to `app/data/` for the next open.
