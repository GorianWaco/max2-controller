#!/usr/bin/env python3
"""Generate circular disc textures for the SL wearable (512×512, transparent corners)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def _lerp(a: tuple[int, ...], b: tuple[int, ...], t: float) -> tuple[int, ...]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(4))


def make_disc(
    path: Path,
    inner: tuple[int, int, int],
    outer: tuple[int, int, int],
    rim: tuple[int, int, int],
    led: tuple[int, int, int],
    highlight: bool = True,
) -> None:
    s = 512
    cx = cy = s // 2
    r = 246
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    px = im.load()
    for y in range(s):
        for x in range(s):
            dx = x + 0.5 - cx
            dy = y + 0.5 - cy
            d = (dx * dx + dy * dy) ** 0.5
            if d > r + 1.2:
                continue
            edge = max(0.0, min(1.0, (r - d) / 4.5))
            t = max(0.0, min(1.0, d / r))
            col = _lerp(inner + (255,), outer + (255,), t * t)
            if d > r - 10:
                mix = max(0.0, min(1.0, (d - (r - 10)) / 10.0))
                col = _lerp(col, rim + (255,), mix)
            a = int(255 * edge)
            px[x, y] = (col[0], col[1], col[2], a)

    if highlight:
        gloss = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        g = ImageDraw.Draw(gloss)
        g.ellipse((90, 55, 400, 230), fill=(255, 255, 255, 48))
        gloss = gloss.filter(ImageFilter.GaussianBlur(18))
        im = Image.alpha_composite(im, gloss)

    draw = ImageDraw.Draw(im)
    # center LED
    draw.ellipse((cx - 22, cy - 22, cx + 22, cy + 22), fill=led + (255,))
    draw.ellipse((cx - 10, cy - 14, cx + 6, cy + 2), fill=(255, 255, 255, 160))
    # thin outer ring
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=rim + (220,), width=5)

    im.save(path, "PNG")
    print("wrote", path)


def main() -> None:
    here = Path(__file__).resolve().parent
    make_disc(
        here / "lovense_offline.png",
        inner=(70, 62, 78),
        outer=(36, 32, 42),
        rim=(120, 110, 128),
        led=(160, 150, 168),
        highlight=False,
    )
    make_disc(
        here / "lovense_online.png",
        inner=(232, 96, 148),
        outer=(148, 28, 78),
        rim=(255, 190, 214),
        led=(255, 230, 240),
        highlight=True,
    )
    make_disc(
        here / "lovense_active.png",
        inner=(255, 70, 130),
        outer=(176, 12, 64),
        rim=(255, 220, 230),
        led=(255, 255, 255),
        highlight=True,
    )


if __name__ == "__main__":
    main()
