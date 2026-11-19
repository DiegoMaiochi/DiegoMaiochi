"""Turn a photo into the ASCII portrait used by the hero card.

Usage:
    python scripts/make_portrait.py [image-path-or-url]

With no argument it downloads the GitHub avatar of the user in profile.json.
The background is detected from the image corners and left blank, so a photo
with a plain background works best. Output: data/portrait.txt
"""

import io
import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent.parent
COLS = 64
# A monospace cell is ~0.6 wide and 1.0 tall, so sample fewer rows than columns.
CELL_ASPECT = 0.6
RAMP = " .:-=+*#%@"  # light text on a dark card: denser = brighter
# Background test: same hue as the corners (chromaticity distance) and not
# much darker. Handles gradients/vignettes in studio-style backgrounds.
HUE_TOLERANCE = 0.045
MIN_BG_BRIGHTNESS = 0.45


def load(src: str) -> Image.Image:
    if src.startswith("http"):
        req = urllib.request.Request(src, headers={"User-Agent": "readme-cards"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return Image.open(io.BytesIO(r.read())).convert("RGB")
    return Image.open(src).convert("RGB")


def background_color(img: Image.Image) -> tuple:
    w, h = img.size
    k = max(4, w // 20)
    px = []
    for x0, y0 in ((0, 0), (w - k, 0), (0, h // 3), (w - k, h // 3)):
        crop = img.crop((x0, y0, x0 + k, y0 + k))
        px += [crop.getpixel((i, j)) for j in range(k) for i in range(k)]
    px.sort(key=sum)
    return px[len(px) // 2]


def chroma(c: tuple) -> tuple:
    s = sum(c) or 1
    return (c[0] / s, c[1] / s, c[2] / s)


def is_background(c: tuple, bg: tuple) -> bool:
    a, b = chroma(c), chroma(bg)
    hue_dist = sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
    return hue_dist < HUE_TOLERANCE and sum(c) > MIN_BG_BRIGHTNESS * sum(bg)


def portrait(img: Image.Image, cols: int = COLS) -> list[str]:
    rows = round(cols * CELL_ASPECT * img.height / img.width)
    bg = background_color(img)
    small = img.resize((cols, rows), Image.LANCZOS)
    gray = ImageOps.grayscale(img).filter(ImageFilter.SHARPEN)
    gray = ImageOps.autocontrast(gray.resize((cols, rows), Image.LANCZOS), cutoff=2)

    lines = []
    for y in range(rows):
        line = []
        for x in range(cols):
            r, g, b = small.getpixel((x, y))
            if is_background((r, g, b), bg):
                line.append(" ")
                continue
            lum = gray.getpixel((x, y)) / 255
            # Never fall back to a blank inside the figure, so dark hair and
            # clothes still draw a silhouette.
            idx = 1 + round(lum * (len(RAMP) - 2))
            line.append(RAMP[idx])
        lines.append("".join(line).rstrip())
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def main() -> None:
    profile = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
    src = sys.argv[1] if len(sys.argv) > 1 else (
        f"https://avatars.githubusercontent.com/{profile['username']}?s=400"
    )
    lines = portrait(load(src))
    out = ROOT / "data" / "portrait.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n{len(lines)} rows -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
