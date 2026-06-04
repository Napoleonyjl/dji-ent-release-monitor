#!/usr/bin/env python3
"""Offline unit checks for app/pdf_parser.py.

These exercise the text/line-level parsing heuristics with a synthetic DJI
Release Notes text block — no real PDF and no network required. Run after any
change to the parser:

    python3 scripts/test_parser.py

Exit code 0 = all good. This is intentionally dependency-free (only stdlib +
the project module) so it runs even without pdfplumber installed... except that
importing pdf_parser imports pdfplumber at module load. If pdfplumber is not
installed, install requirements first (see scripts/dev_run.sh) or run inside the
dev venv:  ../.devvenv/bin/python scripts/test_parser.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app.pdf_parser import (  # noqa: E402
    _parse_date,
    _parse_firmware_table,
    _parse_whats_new,
    DATE_LINE_RE,
)

SAMPLE = """\
DJI Dock 3 Release Notes
Date: 2026.05.08
Dock Firmware: v17.01.05.06
Aircraft Firmware: v17.01.05.06
Remote Controller Firmware: v17.01.05.06
DJI Assistant 2: v2.1.20
* Make sure to update the firmware to the latest version.

What's new
- Added support for the new payload.
- Improved transmission stability and
  reduced video latency in weak-signal areas.

Bug Fixes
- Fixed an occasional RTK dropout.
"""

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}  {detail}")
        failures.append(name)


def main() -> int:
    lines = SAMPLE.splitlines()

    # 1) Date
    check("date parses to 2026-05-08", _parse_date(SAMPLE) == date(2026, 5, 8),
          f"got {_parse_date(SAMPLE)!r}")

    # 2) Firmware table
    date_idx = next(i for i, ln in enumerate(lines) if DATE_LINE_RE.search(ln))
    fw = _parse_firmware_table(lines, date_idx)
    labels = [f["label"] for f in fw]
    check("firmware has 4 rows", len(fw) == 4, f"got {labels}")
    check("firmware stops before '*' note", "Make sure to update the firmware"
          not in " ".join(labels))
    check("firmware captures 'Dock Firmware'", "Dock Firmware" in labels, str(labels))
    check("firmware captures 'DJI Assistant 2'", "DJI Assistant 2" in labels, str(labels))

    # 3) What's new (with wrapped-line continuation joined)
    wn = _parse_whats_new(lines)
    check("whats_new has 2 bullets", len(wn) == 2, f"got {wn}")
    check("wrapped bullet is joined",
          any("weak-signal areas" in b and "Improved transmission" in b for b in wn),
          f"got {wn}")
    check("whats_new stops before Bug Fixes",
          all("RTK dropout" not in b for b in wn), f"got {wn}")

    print()
    if failures:
        print(f"{len(failures)} check(s) FAILED")
        return 1
    print("All parser checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
