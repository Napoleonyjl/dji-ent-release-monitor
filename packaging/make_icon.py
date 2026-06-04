#!/usr/bin/env python3
"""Generate the 1024x1024 app-icon PNG for "DJI ENT Release Monitor".

Usage:
    python3 make_icon.py [output_png]

Default output: ./AppIcon_1024.png  (next to this script)

Requires Pillow. The build script (build_macos_app.sh) turns this PNG into a
multi-resolution .icns via `sips` + `iconutil`. You normally do NOT need to run
this by hand — a prebuilt AppIcon.icns is committed in this folder. Re-run only
if you want to change the icon artwork.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 1024


def load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("AppIcon_1024.png")

    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Rounded-square background with a vertical navy -> blue gradient.
    radius = 230
    top, bot = (16, 24, 43), (24, 52, 104)
    grad = Image.new("RGBA", (S, S), (0, 0, 0, 255))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        gd.line(
            [(0, y), (S, y)],
            fill=(
                int(top[0] + (bot[0] - top[0]) * t),
                int(top[1] + (bot[1] - top[1]) * t),
                int(top[2] + (bot[2] - top[2]) * t),
                255,
            ),
        )
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S, S], radius=radius, fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)

    # Radar rings + sweep wedge + blip (the "monitoring" motif).
    cx, cy = S // 2, int(S * 0.40)
    accent = (64, 196, 255)
    for i, rr in enumerate([300, 220, 140]):
        a = 70 - i * 14
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(*accent, a), width=10)
    wedge = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(wedge).pieslice(
        [cx - 300, cy - 300, cx + 300, cy + 300], start=-115, end=-55, fill=(*accent, 70)
    )
    img.alpha_composite(wedge)
    d = ImageDraw.Draw(img)
    bx = cx + int(150 * math.cos(math.radians(-72)))
    by = cy + int(150 * math.sin(math.radians(-72)))
    d.ellipse([bx - 22, by - 22, bx + 22, by + 22], fill=(120, 230, 255, 255))

    def centered(text: str, font: ImageFont.FreeTypeFont, y: int, fill) -> None:
        bbox = d.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        d.text(((S - w) / 2 - bbox[0], y - bbox[1]), text, font=font, fill=fill)

    centered("DJI", load_font(300, bold=True), int(S * 0.52), (255, 255, 255, 255))
    centered("RELEASE", load_font(96, bold=True), int(S * 0.80), (150, 200, 240, 255))

    img.save(out)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
