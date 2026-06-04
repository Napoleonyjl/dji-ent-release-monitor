# AGENTS.md

This folder is a **skill bundle** for the *DJI ENT Release Monitor* — a FastAPI
WebUI that scrapes DJI enterprise download pages, parses Release Notes PDFs, and
ships as a self-contained macOS `.app`.

**Start here:** read [`SKILL.md`](./SKILL.md) for the full orientation, then the
docs in [`reference/`](./reference/).

## Where things are
- Editable source (the actual app): [`src/`](./src/) — entry point `src/app/main.py`.
- Single-file WebUI: `src/app/static/index.html`.
- Fragile, DJI-dependent logic: `src/app/scraper.py` + `src/app/pdf_parser.py`
  (read [`reference/scraping-and-parsing.md`](./reference/scraping-and-parsing.md) first).
- macOS packaging: [`packaging/`](./packaging/) (build with `packaging/build_macos_app.sh`).

## Common commands
```bash
scripts/dev_run.sh        # run locally with hot-reload -> http://127.0.0.1:8000
scripts/test_parser.py    # offline PDF-parser checks (run inside .devvenv)
scripts/smoke_test.sh     # parser checks + boot server + hit / and /api/releases
packaging/build_macos_app.sh   # -> dist/DJI ENT Release Monitor.{app,zip}
```

## Rules of thumb
- Per-product failures must stay non-fatal (use `errors[]` / `parse_warnings[]`).
- `scraper.py` uses only the Python standard library — keep it that way.
- After changing `src/`, bump `packaging/VERSION` before rebuilding the app
  (the runtime only re-syncs its copy when the version string changes).
- If you change the `/api/releases` JSON shape, update `static/index.html` to match.
- Verify changes with `scripts/smoke_test.sh` (and `scripts/test_parser.py` for parser edits).
