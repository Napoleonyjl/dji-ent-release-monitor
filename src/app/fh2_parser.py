"""Fetch and parse the latest DJI FlightHub 2 HTML release note.

The FlightHub 2 documentation site is a client-rendered VuePress application.
Jina Reader renders the page and returns Markdown, which we reduce to a small,
safe block schema for the release monitor frontend.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date

from .scraper import USER_AGENT


JINA_READER_BASE = "https://r.jina.ai/http://"
MARKDOWN_CONTENT_MARKER = "Markdown Content:"
DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)$")
LIST_RE = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
VERSION_RE = re.compile(r"\b[Vv](\d+(?:\.\d+)+)\b")
PRIVATE_RELEASE_HEADING_RE = re.compile(
    r"^##\s+.*\d{4}-\d{1,2}-\d{1,2}.*(?:私有版|\bv\d)",
    re.IGNORECASE,
)
PUBLIC_RELEASE_LINE_RE = re.compile(r"^(?:#{1,6}\s+)?\d{4}-\d{1,2}-\d{1,2}\b")


@dataclass
class ParsedFH2Release:
    release_date: date | None
    version: str | None = None
    content_blocks: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class FH2Error(Exception):
    pass


def _reader_url(source_url: str) -> str:
    parsed = urllib.parse.urlsplit(source_url)
    if parsed.scheme != "https" or parsed.netloc != "fh.dji.com":
        raise FH2Error("FH2 source URL must use https://fh.dji.com/")
    target = urllib.parse.urlunsplit(
        ("http", parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )
    return JINA_READER_BASE + target.removeprefix("http://")


def fetch_fh2_markdown(source_url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(
        _reader_url(source_url),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/plain",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise FH2Error(f"Failed to fetch rendered FH2 release page: {exc}") from exc


def _markdown_body(markdown: str) -> str:
    if MARKDOWN_CONTENT_MARKER in markdown:
        return markdown.split(MARKDOWN_CONTENT_MARKER, 1)[1].lstrip()
    return markdown.strip()


def _parse_date(text: str) -> date | None:
    match = DATE_RE.search(text)
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def _is_release_start(line: str, edition: str) -> bool:
    stripped = line.strip()
    if edition == "private":
        return bool(PRIVATE_RELEASE_HEADING_RE.match(stripped))
    return bool(PUBLIC_RELEASE_LINE_RE.match(stripped))


def _latest_release_lines(body: str, edition: str) -> tuple[list[str], date | None, str | None]:
    lines = body.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if _is_release_start(line, edition)),
        None,
    )
    if start is None:
        return [], None, None

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if _is_release_start(lines[index], edition):
            end = index
            break

    title = re.sub(r"^#{1,6}\s+", "", lines[start].strip())
    parsed_date = _parse_date(title)
    version_match = VERSION_RE.search(title)
    version = f"V{version_match.group(1)}" if version_match else None
    return lines[start:end], parsed_date, version


def _plain_text(markdown: str) -> str:
    text = LINK_RE.sub(lambda match: match.group(1), markdown)
    text = re.sub(r"(`+)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"\1", text)
    text = text.replace(r"\*", "*")
    text = re.sub(r"\s+\*$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _content_blocks(lines: list[str]) -> list[dict]:
    blocks: list[dict] = []
    list_items: list[str] = []
    paragraphs: list[str] = []

    def flush_list() -> None:
        if list_items:
            blocks.append({"type": "list", "items": list_items.copy()})
            list_items.clear()

    def flush_paragraph() -> None:
        if paragraphs:
            text = _plain_text(" ".join(paragraphs))
            if text:
                blocks.append({"type": "paragraph", "text": text})
            paragraphs.clear()

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            flush_list()
            flush_paragraph()
            continue

        image_match = IMAGE_RE.match(stripped)
        if image_match:
            flush_list()
            flush_paragraph()
            continue

        heading_match = HEADING_RE.match(stripped)
        if heading_match:
            flush_list()
            flush_paragraph()
            text = _plain_text(heading_match.group(2))
            if text:
                blocks.append(
                    {
                        "type": "heading",
                        "level": min(max(len(heading_match.group(1)), 2), 4),
                        "text": text,
                    }
                )
            continue

        list_match = LIST_RE.match(raw_line)
        if list_match:
            flush_paragraph()
            text = _plain_text(list_match.group(2))
            if text:
                list_items.append(text)
            continue

        if (
            (stripped.startswith("**") and stripped.endswith("**"))
            or (stripped.startswith("__") and stripped.endswith("__"))
        ):
            flush_list()
            flush_paragraph()
            text = _plain_text(stripped)
            if text:
                blocks.append({"type": "heading", "level": 3, "text": text})
            continue

        flush_list()
        paragraphs.append(stripped)

    flush_list()
    flush_paragraph()
    return blocks


def parse_fh2_markdown(
    markdown: str,
    *,
    edition: str,
    source_url: str,
) -> ParsedFH2Release:
    if edition not in {"public", "private"}:
        raise ValueError("FH2 edition must be 'public' or 'private'")

    body = _markdown_body(markdown)
    release_lines, release_date, version = _latest_release_lines(body, edition)
    if not release_lines:
        raise FH2Error("Could not find an FH2 release section in rendered Markdown")

    result = ParsedFH2Release(release_date=release_date, version=version)
    if release_date is None:
        result.warnings.append("Could not parse the latest FH2 release date")
    result.content_blocks = _content_blocks(release_lines)
    if not result.content_blocks:
        raise FH2Error("Latest FH2 release section contained no usable content")
    return result


def scrape_fh2_release(source_url: str, edition: str) -> ParsedFH2Release:
    markdown = fetch_fh2_markdown(source_url)
    return parse_fh2_markdown(
        markdown,
        edition=edition,
        source_url=source_url,
    )
