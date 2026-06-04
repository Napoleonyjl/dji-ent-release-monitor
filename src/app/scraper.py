"""Scrape a DJI product downloads page and grab the Release Notes PDF.

The DJI enterprise download pages are server-rendered: the Release Notes PDF
URL, the listing date, and the row label are all present in the initial HTML.
That means we can use plain HTTP — no headless browser needed.

Strategy:
  1. GET the product page.
  2. Locate the row whose visible label contains "Release Notes" (and the
     product name, to avoid matching unrelated items like
     "DJI Assistant 2 Release Notes" that show up on every product page).
  3. From that row, extract the .pdf href and the date string shown next to it.
  4. Download the PDF.

Selectors / regex last verified against
https://enterprise.dji.com/dock-3/downloads on 2026-06-04.
"""

from __future__ import annotations

import re
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Each download anchor in the page has a data-ga-label attribute like:
#   data-ga-label="dowload-DJI Dock 3 - Release Notes"
# (Note: DJI's HTML really does have the typo "dowload-".) This is a far more
# reliable anchor than fishing rows out of structural HTML — the attribute is
# explicit about both the product name and that it's a Release Notes link.
ANCHOR_RE = re.compile(
    r"href=\"([^\"]+\.pdf)\"[^>]*data-ga-label=\"dowload-([^\"]+)\"",
    re.IGNORECASE,
)
# The listing date for a given anchor lives in a nearby
#   <div class="...items-data...">2026-05-08</div>
# We pair anchors to dates by scanning the HTML for the items-name/items-data
# pair whose name matches the anchor's label.
ROW_RE = re.compile(
    r"items-name[^>]*>([^<]+?)</div>\s*<div[^>]*items-data[^>]*>([^<]+?)</div>",
    re.IGNORECASE,
)
RELEASE_NOTES_LABEL_RE = re.compile(
    r"(release\s*notes?|发布记录|发布说明|版本说明|发行说明)", re.IGNORECASE
)


@dataclass
class ScrapedRelease:
    product: str
    pdf_path: Path
    pdf_url: str
    listing_date: str | None
    listing_label: str | None
    page_url: str
    language: str


class ScrapeError(Exception):
    pass


def _http_get(url: str, timeout: int = 30) -> bytes:
    # Some DJI PDF URLs contain literal spaces in the path; urllib refuses
    # those as "control characters". Re-quote the path component so spaces and
    # other unsafe chars become %20.
    parsed = urllib.parse.urlsplit(url)
    safe_path = urllib.parse.quote(parsed.path, safe="/%")
    safe_url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, safe_path, parsed.query, parsed.fragment)
    )
    req = urllib.request.Request(safe_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _localized_page_url(url: str, language: str) -> str:
    """Return the DJI downloads page for the requested site language."""
    if language != "zh":
        return url

    parsed = urllib.parse.urlsplit(url)
    parts = [p for p in parsed.path.split("/") if p]
    known_locales = {
        "cn",
        "de",
        "es",
        "fr",
        "jp",
        "kr",
        "nl",
        "pt",
        "zh-tw",
        "mobile",
    }
    if parts and parts[0].lower() in known_locales:
        parts[0] = "cn"
    else:
        parts.insert(0, "cn")
    new_path = "/" + "/".join(parts)
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, new_path, parsed.query, parsed.fragment)
    )


def _candidate_pdf_urls(pdf_url: str, language: str) -> list[str]:
    """Prefer DJI's Chinese PDF sibling when the CN page links to an EN file."""
    if language != "zh":
        return [pdf_url]

    candidates: list[str] = []

    def add(url: str) -> None:
        if url not in candidates:
            candidates.append(url)

    def add_variant(url: str) -> None:
        if url != pdf_url:
            add(url)

    def replace_locale_token(match: re.Match) -> str:
        prefix = match.group(1)
        suffix = match.group(2) or ""
        extension = match.group(3)
        return f"{prefix}cn{suffix}{extension}"

    add_variant(
        re.sub(
            r"([_-])en(\d*)(\.pdf)$",
            replace_locale_token,
            pdf_url,
            flags=re.IGNORECASE,
        )
    )
    add_variant(re.sub(r"([_-])EN(\d*)(\.pdf)$", r"\1CN\2\3", pdf_url))
    add_variant(re.sub(r"([_-])En(\d*)(\.pdf)$", r"\1Cn\2\3", pdf_url))
    add_variant(
        re.sub(r"([_-])english(\.pdf)$", r"\1chinese\2", pdf_url, flags=re.IGNORECASE)
    )
    add_variant(re.sub(r"([/_-])EN([/_-])", r"\1CN\2", pdf_url))
    add_variant(re.sub(r"([/_-])en([/_-])", r"\1cn\2", pdf_url))
    add(pdf_url)
    return candidates


def _looks_like_release_notes(label: str) -> bool:
    return bool(RELEASE_NOTES_LABEL_RE.search(label))


def _find_release_notes_row(html: str, product_name: str) -> tuple[str, str | None, str]:
    """Return (label, date_str_or_None, pdf_url) for the row matching this
    product's Release Notes entry.

    Preference order:
      1. An anchor whose data-ga-label contains BOTH "release notes" AND a
         meaningful token from the product name (e.g. "Dock 3", "Matrice 350").
      2. Any "release notes" anchor — fallback.
    """
    anchors: list[tuple[str, str]] = []  # (label, href)
    for m in ANCHOR_RE.finditer(html):
        href = m.group(1).strip()
        label = re.sub(r"\s+", " ", m.group(2)).strip()
        if not _looks_like_release_notes(label):
            continue
        anchors.append((label, href))

    if not anchors:
        raise ScrapeError("No Release Notes download anchors found on page")

    name_tokens = re.findall(r"[A-Za-z0-9]+", product_name)
    name_tokens = [t for t in name_tokens if t.lower() != "dji"]

    def score(label: str) -> int:
        ll = label.lower()
        s = 0
        for tok in name_tokens:
            if tok.lower() in ll:
                s += 10
        # Generic items that appear on every product page
        if "assistant" in ll and not any("assistant" in t.lower() for t in name_tokens):
            s -= 5
        if "thermal analysis" in ll and not any(
            "thermal" in t.lower() for t in name_tokens
        ):
            s -= 5
        if "pilot" in ll and not any("pilot" in t.lower() for t in name_tokens):
            s -= 5
        return s

    anchors.sort(key=lambda a: score(a[0]), reverse=True)
    best_label, best_href = anchors[0]

    # Now find the listing date for this row. The items-name div text usually
    # matches the anchor label (the page has minor whitespace/punctuation
    # differences). We search row-by-row for the closest text match.
    listing_date: str | None = None
    best_label_lower = best_label.lower()
    for m in ROW_RE.finditer(html):
        row_label = re.sub(r"\s+", " ", m.group(1)).strip()
        row_date = m.group(2).strip()
        if row_label.lower() == best_label_lower or (
            _looks_like_release_notes(row_label)
            and all(tok.lower() in row_label.lower() for tok in name_tokens)
        ):
            listing_date = row_date
            break

    return best_label, listing_date, best_href


def _download_pdf(pdf_url: str, language: str) -> tuple[str, bytes]:
    errors: list[str] = []
    for candidate in _candidate_pdf_urls(pdf_url, language):
        try:
            pdf_bytes = _http_get(candidate, timeout=60)
        except Exception as e:
            errors.append(f"{candidate}: {e}")
            continue
        if pdf_bytes.startswith(b"%PDF"):
            return candidate, pdf_bytes
        errors.append(f"{candidate}: downloaded content is not a PDF")
    raise ScrapeError("Failed to download a valid PDF: " + " | ".join(errors))


def scrape_product(name: str, url: str, language: str = "en") -> ScrapedRelease:
    """Fetch the product page, find the Release Notes PDF, download it.

    Raises ScrapeError on any recoverable failure (caller wraps in try/except).
    """
    page_url = _localized_page_url(url, language)
    try:
        html_bytes = _http_get(page_url, timeout=30)
    except Exception as e:
        raise ScrapeError(f"Failed to fetch product page: {e}") from e

    html = html_bytes.decode("utf-8", errors="replace")

    label, listing_date, pdf_url = _find_release_notes_row(html, name)

    try:
        final_pdf_url, pdf_bytes = _download_pdf(pdf_url, language)
    except Exception as e:
        raise ScrapeError(f"Failed to download PDF {pdf_url}: {e}") from e

    tmp = Path(tempfile.gettempdir()) / f"dji_release_{abs(hash(final_pdf_url))}.pdf"
    tmp.write_bytes(pdf_bytes)

    return ScrapedRelease(
        product=name,
        pdf_path=tmp,
        pdf_url=final_pdf_url,
        listing_date=listing_date,
        listing_label=label,
        page_url=page_url,
        language=language,
    )
