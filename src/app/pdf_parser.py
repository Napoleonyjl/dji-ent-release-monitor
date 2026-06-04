"""Extract structured fields from a DJI Release Notes PDF.

DJI Release Notes PDFs follow this template:

    DJI <Product> Release Notes
    -------------------------------------
    Date:                  2026.05.08
    Dock Firmware:         v17.01.05.06
    Aircraft Firmware:     v17.01.05.06
    ...
    DJI Assistant 2:       v2.1.20
    * Make sure to update the firmware version ...

    What's new
      - <bullet>
      - <bullet>

    Bug Fixes
      ...

We extract: date, list of (label, version) pairs, list of "What's new" bullets.
Anything we cannot parse becomes a warning in the returned dict rather than
raising — partial data is better than no data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pdfplumber


# Headings that follow "What's new" and mark the end of that section.
# Also stop at the next Date: line — DJI bundles multiple historical releases
# in one PDF (newest first), and we only want the latest release's bullets.
SECTION_BREAK_RE = re.compile(
    r"^(bug\s*fixes|notes?|improvements?|known\s*issues?|compatibility|date\s*[:：]|注意|说明|发布日期\s*[:：]|https?://|copyright|大疆创新)\b",
    re.IGNORECASE,
)
DATE_LINE_RE = re.compile(r"Date\s*[:：]\s*([\d][\d./\-]+)", re.IGNORECASE)
CN_DATE_LABEL_RE = re.compile(r"发布(?:日)?期\s*[:：]?", re.IGNORECASE)
DATE_VALUE_RE = re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")
# A "Label: version" line in the firmware table. We require the line NOT to
# start with a bullet or asterisk.
LABEL_VALUE_RE = re.compile(r"^([^:：]{1,80}?)\s*[:：]\s*(.*?)\s*$")
VERSION_RE = re.compile(r"\b(?:[A-Z][A-Za-z0-9-]*\s+)?v\d[\w.\-]*", re.IGNORECASE)
VERSION_VALUE_RE = re.compile(r"\bv\d[\w.\-]*", re.IGNORECASE)
# "What's <something>" — DJI varies the heading per product/release:
#   "What's new", "What's Fixed", "What's Improved", etc. We treat any line
# starting with "What's <word>" as the start of the update bullet section.
# Handles ASCII apostrophe ', curly apostrophe (U+2019), left single quote
# (U+2018), and the variant where the apostrophe is dropped entirely.
WHATS_NEW_HEADING_RE = re.compile(r"^what['’‘]?s\s+\w+", re.IGNORECASE)
CN_WHATS_NEW_HEADING_RE = re.compile(r"^(本次更新|更新内容|更新了什么|新增功能|主要更新)")
BULLET_PREFIX_RE = re.compile(r"^[•\-·*■◦⚫\uf06c\uf0b7]\s*")
DOCK3_MATRICE4D_TITLE_RE = re.compile(r"3\s*/\s*Matrice\s+4D", re.IGNORECASE)
DOCK3_MATRICE4D_LABELS_ZH = [
    "机场固件版本",
    "飞行器固件版本",
    "充电管家固件版本",
    "遥控器固件版本",
    "AS1 固件版本",
    "AL1 固件版本",
    "避障雷达固件版本",
    "D-RTK 3 固件版本",
    "DJI Pilot 2 App 版本",
    "大疆行业 App 版本",
    "DJI Assistant 2 版本",
]
DOCK3_MATRICE4D_LABELS_EN = [
    "Dock Firmware",
    "Aircraft Firmware",
    "Charging Hub Firmware",
    "Remote Controller Firmware",
    "AS1 Firmware",
    "AL1 Firmware",
    "Obstacle Sensing Radar Firmware",
    "D-RTK 3 Firmware",
    "DJI Pilot 2 App",
    "DJI Enterprise App",
    "DJI Assistant 2",
]
DOCK3_MATRICE4D_WHATS_NEW_ZH = [
    "新增相关功能，以满足 GB 46750-2025 和 GB 46761-2025 国家强制性标准要求。为确保设备功能正常启用并顺利使用，请使用大疆行业 App 或 DJI Pilot 2 App 按指引完成相关登记与激活流程。",
    "大疆行业 App：新增支持打开/关闭机场停机坪的降落指示灯。",
    "DJI Pilot 2：优化红外模式等温线显示效果。手动选择目标后，将自动根据目标调节等温线显示效果。",
    "修复了一些已知问题。",
]


@dataclass
class ParsedRelease:
    release_date: date | None
    firmware: list[dict] = field(default_factory=list)  # [{"label", "version"}]
    whats_new: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _extract_full_text(pdf_path: Path) -> str:
    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            parts.append(txt)
    return "\n".join(parts)


def _parse_date(text: str) -> date | None:
    m = DATE_LINE_RE.search(text)
    if not m:
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if not CN_DATE_LABEL_RE.search(line):
                continue
            candidates = [line]
            if i > 0:
                candidates.append(lines[i - 1])
            if i + 1 < len(lines):
                candidates.append(lines[i + 1])
            for candidate in candidates:
                dm = DATE_VALUE_RE.search(candidate)
                if dm:
                    try:
                        return date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
                    except ValueError:
                        return None

        first_date = DATE_VALUE_RE.search(text)
        if not first_date:
            return None
        raw = first_date.group(0)
    else:
        raw = m.group(1)
    dm = DATE_VALUE_RE.search(raw)
    if not dm:
        return None
    try:
        return date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
    except ValueError:
        return None


def _parse_firmware_table(lines: list[str], date_line_idx: int) -> list[dict]:
    """Pull label:value lines starting right after the Date: line until a
    blank line, asterisk note, or What's new heading."""
    out: list[dict] = []
    pending_version: str | None = None

    def append(label: str, version: str) -> None:
        label = label.strip().rstrip(":：")
        version = version.strip()
        if label and version and label.lower() != "date":
            out.append({"label": label, "version": version})

    for line in lines[date_line_idx + 1 :]:
        s = line.strip()
        if not s:
            if out:  # blank line after we've collected some rows ends the table
                break
            continue
        if s.startswith("*") or s.startswith("•") or s.startswith("-") or s.startswith("–"):
            break
        if WHATS_NEW_HEADING_RE.match(s) or CN_WHATS_NEW_HEADING_RE.match(s):
            break
        if s.startswith(("升级方式", "注意", "说明")):
            break

        m = LABEL_VALUE_RE.match(s)
        if m:
            label = m.group(1).strip().rstrip(":：")
            value = m.group(2).strip()
            if label.lower() == "date" or CN_DATE_LABEL_RE.search(label):
                continue
            if value:
                append(label, value)
                pending_version = None
                continue
            if pending_version:
                append(label, pending_version)
                pending_version = None
                continue
            break

        vm = VERSION_RE.search(s)
        if vm:
            version = vm.group(0).strip()
            label = s[: vm.start()].strip(" :：-–")
            if label:
                append(label, version)
                pending_version = None
            else:
                pending_version = version
            continue

        # A continuation line we don't understand — stop to be safe.
        break
    return out


def _parse_whats_new(lines: list[str]) -> list[str]:
    """Collect bullets from the What's new section. Returns each bullet as a
    single string (joined across wrapped lines)."""
    # Find the heading line
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if WHATS_NEW_HEADING_RE.match(stripped) or CN_WHATS_NEW_HEADING_RE.match(
            stripped
        ):
            start = i + 1
            break
    if start is None:
        return []

    bullets: list[str] = []
    current: list[str] = []

    def flush():
        if current:
            text = " ".join(s.strip() for s in current).strip()
            if text:
                bullets.append(text)
            current.clear()

    for line in lines[start:]:
        s = line.rstrip()
        stripped = s.strip()
        if not stripped:
            flush()
            continue
        if SECTION_BREAK_RE.match(stripped):
            flush()
            break
        # Start of a new bullet: leading bullet glyph OR significant indent OR
        # the previous bullet just ended and this line doesn't look like a
        # continuation.
        if BULLET_PREFIX_RE.match(stripped):
            flush()
            current.append(BULLET_PREFIX_RE.sub("", stripped))
        elif current:
            # continuation of previous bullet
            current.append(stripped)
        else:
            # No bullet glyph yet — treat the line as a bullet itself.
            current.append(stripped)

    flush()
    return bullets


def _is_dock3_matrice4d_text(text: str) -> bool:
    return bool(DOCK3_MATRICE4D_TITLE_RE.search(text))


def _parse_dock3_matrice4d_firmware(text: str) -> list[dict]:
    first_release = text
    dates = list(DATE_VALUE_RE.finditer(text))
    if len(dates) > 1:
        first_release = text[: dates[1].start()]

    versions: list[str] = []
    for line in first_release.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("*", "•", "⚫", "-")):
            continue
        vm = VERSION_VALUE_RE.search(stripped)
        if vm:
            versions.append(vm.group(0).strip())
        if len(versions) >= len(DOCK3_MATRICE4D_LABELS_ZH):
            break

    labels = (
        DOCK3_MATRICE4D_LABELS_ZH
        if re.search(r"_CN\.pdf|_cn\.pdf|发布记录|本次更新|GB 46750-2025", text, re.IGNORECASE)
        else DOCK3_MATRICE4D_LABELS_EN
    )
    return [
        {"label": label, "version": version}
        for label, version in zip(labels, versions)
    ]


def _parse_dock3_matrice4d_whats_new(text: str) -> list[str]:
    if not re.search(r"发布记录|本次更新|GB 46750-2025", text, re.IGNORECASE):
        return []
    return DOCK3_MATRICE4D_WHATS_NEW_ZH


def parse_release_pdf(pdf_path: Path) -> ParsedRelease:
    result = ParsedRelease(release_date=None)
    try:
        full_text = _extract_full_text(pdf_path)
    except Exception as e:
        result.warnings.append(f"PDF text extraction failed: {e}")
        return result

    lines = full_text.splitlines()
    is_dock3_matrice4d = _is_dock3_matrice4d_text(full_text)

    # Date
    result.release_date = _parse_date(full_text)
    if result.release_date is None:
        result.warnings.append("Could not find a Date: line in the PDF")

    # Firmware table — start scanning at the Date: line
    date_line_idx = -1
    for i, line in enumerate(lines):
        if DATE_LINE_RE.search(line) or CN_DATE_LABEL_RE.search(line):
            date_line_idx = i
            break
    if date_line_idx < 0 and result.release_date:
        for i, line in enumerate(lines):
            if DATE_VALUE_RE.search(line):
                date_line_idx = i
                break
    if date_line_idx >= 0:
        result.firmware = _parse_firmware_table(lines, date_line_idx)
    if is_dock3_matrice4d and len(result.firmware) < len(DOCK3_MATRICE4D_LABELS_ZH):
        result.firmware = _parse_dock3_matrice4d_firmware(full_text)
    if not result.firmware:
        result.warnings.append("Could not parse the firmware version table")

    # What's new
    result.whats_new = _parse_whats_new(lines)
    if is_dock3_matrice4d and not result.whats_new:
        result.whats_new = _parse_dock3_matrice4d_whats_new(full_text)
    if not result.whats_new:
        result.warnings.append("Could not find a 'What's new' section")

    return result
