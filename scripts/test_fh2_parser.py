#!/usr/bin/env python3
"""Offline checks for the FlightHub 2 Markdown parser."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app.fh2_parser import FH2Error, parse_fh2_markdown  # noqa: E402


PUBLIC_ZH = """\
Title: 大疆司空 2

URL Source: http://fh.dji.com/example

Published Time: Thu, 11 Jun 2026 00:00:00 GMT

Markdown Content:
2026-5-27 版本公告

【新功能支持】

![功能截图](/user-manual/local-image/new.png)

**OpenAPI V2.0 公有云版发布**

* 新增查询接口。
* 支持[接口文档](https://example.com/docs)。

2026-05-08 版本公告

* 旧版本内容。
"""

PUBLIC_EN = """\
Markdown Content:
2026-05-27

What's New

![Image 1](https://fh.dji.com/user-manual/local-image/new-en.webp)

* Added a new feature.

2026-05-08

* Previous release.
"""

PRIVATE_ZH = """\
Markdown Content:
* [2026-04-29 私有版 V1.5](https://fh.dji.com/example#v1-5)
* [2025-12-23 私有版 V1.4](https://fh.dji.com/example#v1-4)

#### **发布列表**

## 2026-4-29 私有版 V1.5

**一、公有版能力对齐**

1. 支持超清全景。
   * 支持自动拼接。

14、不支持 Copilot 相关能力 *

![bad](https://example.com/not-allowed.png)

## 2025-12-23 私有版 V1.4

* 旧版本内容。
"""


failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}  {detail}")
        failures.append(name)


def main() -> int:
    public_zh = parse_fh2_markdown(
        PUBLIC_ZH,
        edition="public",
        source_url="https://fh.dji.com/user-manual/cn/release-notes/release-notes-public.html",
    )
    check("public zh date is normalized", public_zh.release_date == date(2026, 5, 27))
    check(
        "public parser stops before previous release",
        all("旧版本" not in str(block) for block in public_zh.content_blocks),
    )
    check(
        "public images are omitted",
        not any(block.get("type") == "image" for block in public_zh.content_blocks),
        str(public_zh.content_blocks),
    )
    check(
        "link markup becomes readable text",
        any("接口文档" in str(block) and "](" not in str(block) for block in public_zh.content_blocks),
    )

    public_en = parse_fh2_markdown(
        PUBLIC_EN,
        edition="public",
        source_url="https://fh.dji.com/user-manual/en/release-notes/release-notes-public.html",
    )
    check("public en content is parsed", any("Added a new feature" in str(b) for b in public_en.content_blocks))

    private_zh = parse_fh2_markdown(
        PRIVATE_ZH,
        edition="private",
        source_url="https://fh.dji.com/user-manual/cn/release-notes/release-notes-private.html",
    )
    check("private directory is skipped", private_zh.release_date == date(2026, 4, 29))
    check("private version is parsed", private_zh.version == "V1.5", str(private_zh.version))
    check(
        "dangling Markdown marker is removed",
        any(
            block.get("text") == "14、不支持 Copilot 相关能力"
            for block in private_zh.content_blocks
        ),
        str(private_zh.content_blocks),
    )
    check(
        "private parser stops before previous release",
        all("旧版本" not in str(block) for block in private_zh.content_blocks),
    )
    check(
        "private images are omitted",
        not any(block.get("type") == "image" for block in private_zh.content_blocks),
        str(private_zh.content_blocks),
    )

    try:
        parse_fh2_markdown(
            "Markdown Content:\nNo dated releases here.",
            edition="public",
            source_url="https://fh.dji.com/user-manual/en/release-notes/release-notes-public.html",
        )
    except FH2Error:
        malformed_rejected = True
    else:
        malformed_rejected = False
    check("missing release section is an error", malformed_rejected)

    print()
    if failures:
        print(f"{len(failures)} check(s) FAILED")
        return 1
    print("All FH2 parser checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
