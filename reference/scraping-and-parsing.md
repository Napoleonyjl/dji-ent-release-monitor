# Scraping & parsing — assumptions and how to fix them

`scraper.py` and `pdf_parser.py` are the only fragile parts. They depend on
DJI's current website HTML and PDF template, which change without notice. This
doc captures every assumption so you can re-verify and repair quickly.

## 1. Finding the Release Notes PDF (`scraper.py`)

DJI download pages are **server-rendered** — everything we need is in the initial
HTML, so plain `urllib` works (no browser/JS).

### Key regexes
- `ANCHOR_RE` matches the download link:
  ```
  href="....pdf" ... data-ga-label="dowload-<LABEL>"
  ```
  **`dowload-` is not a typo on our side — DJI's HTML literally misspells
  "download".** If matching suddenly fails, first check whether DJI fixed the
  spelling or renamed `data-ga-label`.
- `ROW_RE` pairs a visible row name with its listing date:
  ```
  ...items-name...>NAME</div> <div ...items-data...>DATE</div>
  ```

### Selection logic (`_find_release_notes_row`)
1. Collect every anchor whose label contains "release notes".
2. Score each by how many product-name tokens it contains (e.g. "Dock 3",
   "Matrice 350"), with **penalties** for generic items that appear on every
   product page: "DJI Assistant 2", "Thermal Analysis Tool", "DJI Pilot".
3. Pick the highest score. Then find the listing date from the row whose name
   matches the chosen label (or any release-notes row containing all name tokens).

This scoring exists because each product page lists *several* Release Notes
links (the product itself + companion tools). If the wrong PDF is picked, adjust
the token scoring / penalties here.

### Other scraper details
- `USER_AGENT` is a desktop Chrome string. DJI may block empty/odd UAs.
- `_http_get` re-quotes URL paths so DJI PDF URLs containing literal spaces
  become `%20` (urllib otherwise rejects them as "control characters").
- A download must start with `%PDF`, else `ScrapeError` ("not a PDF") — this
  catches HTML error pages served with a `.pdf` URL.

## 2. Parsing the PDF (`pdf_parser.py`)

Expected template (newest release first; one PDF may hold many):

```
DJI <Product> Release Notes
Date:                  2026.05.08
Dock Firmware:         v17.01.05.06
Aircraft Firmware:     v17.01.05.06
...
DJI Assistant 2:       v2.1.20
* Make sure to update ...

What's new
  - <bullet>
  - <bullet, possibly wrapped
    across two lines>

Bug Fixes
  ...
```

### Heuristics
- **Date:** `DATE_LINE_RE` finds `Date:` (ASCII or full-width colon `：`);
  `DATE_VALUE_RE` accepts `YYYY.MM.DD`, `YYYY-MM-DD`, `YYYY/MM/DD`.
- **Firmware table** (`_parse_firmware_table`): starts right after the `Date:`
  line; reads `Label: value` lines; **stops** at a blank line (once rows exist),
  a bullet/`*` note, a `What's …` heading, or a line it can't parse.
- **What's new** (`_parse_whats_new`): starts at the first `What's <word>`
  heading (`WHATS_NEW_HEADING_RE` tolerates `'`/`’`/`‘` or a missing
  apostrophe, and any trailing word — "What's new/Fixed/Improved"). Joins
  wrapped continuation lines into one bullet. **Stops** at `SECTION_BREAK_RE`
  (Bug Fixes / Notes / Improvements / Known Issues / Compatibility / next
  `Date:`).
- Some DJI Chinese PDFs omit Unicode mappings for visible Chinese glyphs. If
  the normal text layer yields no update section, `parse_release_pdf` renders
  the newest pages and runs Tesseract OCR with Simplified Chinese and English
  language data, then feeds the OCR result through the same section parser.
- Each missing piece becomes a `warnings[]` entry; the function never raises.

## 3. How to debug a layout change

Symptoms → likely cause:
- Product shows an **error** card → `scraper` couldn't find the anchor or the
  download wasn't a PDF.
- Product shows but **no firmware / no What's new**, with `parse_warnings` →
  PDF template changed (`pdf_parser`).
- **Wrong PDF** (e.g. shows the Assistant tool's notes) → scoring in
  `_find_release_notes_row`.

Capture fresh inputs (do this from `src/`):

```bash
# Save the raw HTML DJI serves us
python3 - <<'PY'
import urllib.request
from app.scraper import USER_AGENT
url = "https://enterprise.dji.com/dock-3/downloads"
req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
open("/tmp/dji.html","wb").write(urllib.request.urlopen(req, timeout=30).read())
print("saved /tmp/dji.html")
PY

# Dump what the parser sees from a downloaded PDF
python3 - <<'PY'
import pdfplumber
with pdfplumber.open("/tmp/sample.pdf") as pdf:
    print("\n".join((p.extract_text() or "") for p in pdf.pages))
PY
```

Then grep the HTML for `data-ga-label`, `items-name`, `items-data`, `.pdf` to
see the current structure, and adjust the regexes/scoring. After any parser
change run `scripts/test_parser.py` and update its `SAMPLE` to match the new
template.

## 4. Adding / changing monitored products

Edit `src/app/products.json` — an array of `{ "name", "url" }`. `url` must be the
official product **/downloads** page that contains a Release Notes PDF row. The
`name` tokens drive PDF-row scoring, so keep them close to how DJI labels the
product (e.g. "DJI Matrice 350 RTK"). When the UI display name intentionally
differs from DJI's download-row label, add `scrape_name` and keep that value
aligned with DJI's label.
