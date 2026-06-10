# AGENTS.md

This folder is a **skill bundle** for the *DJI ENT Release Monitor* — a FastAPI
WebUI and Cloudflare Pages site that parses DJI PDF and FlightHub 2 HTML release
notes.

**Start here:** read [`SKILL.md`](./SKILL.md) for the full orientation, then the
docs in [`reference/`](./reference/).

## Where things are
- Editable source (the actual app): [`src/`](./src/) — entry point `src/app/main.py`.
- Single-file WebUI: `src/app/static/index.html`.
- Fragile, DJI-dependent logic: `src/app/scraper.py` + `src/app/pdf_parser.py`
  (read [`reference/scraping-and-parsing.md`](./reference/scraping-and-parsing.md) first).
- Static publishing: `scripts/build_static_site.py` and
  [`reference/deploy-cloudflare-pages.md`](./reference/deploy-cloudflare-pages.md).

## Common commands
```bash
scripts/dev_run.sh        # run locally with hot-reload -> http://127.0.0.1:8000
scripts/test_parser.py    # offline PDF-parser checks (run inside .devvenv)
scripts/smoke_test.sh     # parser checks + boot server + hit / and /api/releases
scripts/build_static_site.py   # -> public/ for Cloudflare Pages
```

## Rules of thumb
- Per-product failures must stay non-fatal (use `errors[]` / `parse_warnings[]`).
- `scraper.py` uses only the Python standard library — keep it that way.
- If you change the `/api/releases` JSON shape, update `static/index.html` to match.
- Verify changes with `scripts/smoke_test.sh` (and `scripts/test_parser.py` for parser edits).
- This project is web-only. Do not modify the legacy `packaging/` directory
  unless macOS support is explicitly requested again.
- A change is not complete after local verification. Commit and push it to
  GitHub, deploy Cloudflare Pages, then verify the production site at
  `https://dji-ent-release-monitor.pages.dev`.
