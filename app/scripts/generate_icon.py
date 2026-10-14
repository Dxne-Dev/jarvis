"""Génère l'icône de l'app (sphère de points lumineux) en PNG 1024 px.

Usage : python3 scripts/generate_icon.py src-tauri/app-icon.png
puis : pnpm tauri icon src-tauri/app-icon.png
"""

import math
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SIZE = 1024
SS = 2  # suréchantillonnage
ACCENT = (79, 227, 255)
BG_TOP = (9, 14, 26)
BG_BOTTOM = (3, 5, 10)


def background(size: int) -> Image.Image:
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
    grad = grad.resize((size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * 0.22), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out


def sphere_layer(size: int) -> Image.Image:
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx = cy = size / 2
    radius = size * 0.29
    count = 900
    golden = math.pi * (3 - math.sqrt(5))
    tilt = 0.4
    points = []
    for i in range(count):
        y = 1 - (i + 0.5) * 2 / count
        r = math.sqrt(1 - y * y)
        theta = golden * i
        x, z = math.cos(theta) * r, math.sin(theta) * r
        y2 = y * math.cos(tilt) - z * math.sin(tilt)
        z2 = y * math.sin(tilt) + z * math.cos(tilt)
        points.append((x, y2, z2))
    points.sort(key=lambda p: p[2])
    for x, y, z in points:
        front = (z + 1) / 2
        alpha = int(40 + 215 * front ** 1.6)
        dot = size * (0.0035 + 0.0045 * front)
        px, py = cx + x * radius, cy - y * radius
        mix = 0.15 + 0.55 * front ** 3
        color = tuple(round(c + (255 - c) * mix) for c in ACCENT)
        draw.ellipse((px - dot, py - dot, px + dot, py + dot), fill=(*color, alpha))
    ring = size * 0.405
    width = size * 0.012
    draw.ellipse((cx - ring, cy - ring, cx + ring, cy + ring), outline=(*ACCENT, 210), width=round(width))
    return layer


def core_glow(size: int) -> Image.Image:
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    c = size / 2
    for i in range(40, 0, -1):
        r = size * 0.25 * i / 40
        a = int(5 + 3 * (40 - i))
        draw.ellipse((c - r, c - r, c + r, c + r), fill=(*ACCENT, min(a, 120)))
    return glow.filter(ImageFilter.GaussianBlur(size * 0.04))


def main(path: str) -> None:
    big = SIZE * SS
    base = background(big)
    glow = core_glow(big)
    dots = sphere_layer(big)
    halo = dots.filter(ImageFilter.GaussianBlur(big * 0.012))
    out = Image.alpha_composite(base, Image.composite(glow, Image.new("RGBA", glow.size), base.split()[3]))
    out = Image.alpha_composite(out, ImageChops.multiply(halo, Image.new("RGBA", halo.size, (255, 255, 255, 180))))
    out = Image.alpha_composite(out, dots)
    out.resize((SIZE, SIZE), Image.LANCZOS).save(path)


if __name__ == "__main__":
    main(sys.argv[1])
