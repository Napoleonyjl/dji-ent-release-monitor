# Deploy to Cloudflare Pages

This project can ship as a static Cloudflare Pages site. The live site does not
run FastAPI or parse PDFs on visitor requests. Instead, GitHub Actions runs the
existing Python scraper/parser once per day, writes static JSON, and deploys the
static artifact to Pages.

## Output

`scripts/build_static_site.py` writes:

```text
public/
├── index.html
├── _headers
└── data/
    ├── releases-en.json
    └── releases-zh.json
```

The frontend first loads `data/releases-en.json` or `data/releases-zh.json`.
If those files are not present, it falls back to the local FastAPI
`/api/releases` endpoint for development.

## GitHub Actions schedule

`.github/workflows/deploy-pages.yml` runs:

- manually via `workflow_dispatch`
- daily at `04:10 UTC`

It installs `src/requirements.txt`, runs `scripts/build_static_site.py`, then
deploys `public/` to Cloudflare Pages.

Before building, the workflow restores `.cache/last-known-good` with
`actions/cache`. The build also reads the current Pages JSON and the repository
snapshots, then keeps the newest successful row for each stable `product_id`.

If a source temporarily fails after retries, its previous successful row is
published with `stale: true` and `last_success_at`; the frontend marks the card
as using previous data. If a failed product has no historical row at all, the
build exits non-zero before deployment, so Cloudflare keeps serving the last
complete deployment.

FH2 collection depends on Jina Reader being reachable from GitHub Actions and
uses the same last-known-good policy.

If GitHub rejects workflow commits because your local token lacks the
`workflow` scope, copy `reference/deploy-pages-workflow.yml` to
`.github/workflows/deploy-pages.yml` from the GitHub web UI, or retry the commit
with a token that includes the `workflow` scope.

## Required GitHub secrets

Add these repository secrets before enabling deployment:

```text
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_API_TOKEN
```

The API token should be scoped narrowly for Cloudflare Pages deployment. In
Cloudflare, create a token with permission to edit Cloudflare Pages for the
target account.

## Cloudflare Pages project

The workflow uses:

```text
projectName: dji-ent-release-monitor
directory: public
```

Create a Pages project named `dji-ent-release-monitor`, or update both
`.github/workflows/deploy-pages.yml` and `wrangler.toml` to your chosen project
name.

The default public URL will be:

```text
https://dji-ent-release-monitor.pages.dev
```

You can bind a custom domain later from the Cloudflare Pages dashboard.

## Local verification

```bash
.devvenv/bin/python scripts/build_static_site.py
.devvenv/bin/python -m http.server 8088 --directory public
```

Open:

```text
http://127.0.0.1:8088
```

## Cost profile

This setup should stay on the free tier for normal usage:

- Cloudflare Pages serves static assets.
- No Pages Functions or Workers are invoked for visitor traffic.
- GitHub Actions runs once per day, so private-repo minutes should remain low.

If you increase the schedule frequency, GitHub Actions minutes become the main
cost variable.
