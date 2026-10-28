"""Generates 6 SYNTHETIC placeholder 'property' illustrations (not real photos).
Safe to commit. Run:  python sample_data/generate_sample_images.py
"""
import random
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "images"
OUT.mkdir(parents=True, exist_ok=True)

SKIES = [
    ((255, 183, 94), (120, 170, 230)),
    ((250, 214, 165), (140, 190, 235)),
    ((255, 150, 120), (90, 120, 200)),
    ((200, 220, 250), (120, 170, 230)),
    ((255, 205, 140), (100, 150, 220)),
    ((180, 200, 240), (90, 130, 200)),
]
BODIES = [(226, 214, 196), (205, 190, 170), (235, 225, 210), (190, 175, 160), (220, 200, 185), (210, 210, 215)]


def gradient(w, h, top, bottom):
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)
    return img


def draw_scene(idx):
    w, h = 1600, 1200
    rnd = random.Random(idx)
    top, bottom = SKIES[idx % len(SKIES)]
    img = gradient(w, h, top, bottom)
    d = ImageDraw.Draw(img)
    d.ellipse((w - 380, 90, w - 180, 290), fill=(255, 236, 170))
    ground = int(h * 0.78)
    d.rectangle((0, ground, w, h), fill=(70, 120, 80))
    bw, bh = rnd.randint(560, 820), rnd.randint(420, 660)
    x0, y0 = (w - bw) // 2, ground - bh
    d.rectangle((x0, y0, x0 + bw, ground), fill=BODIES[idx % len(BODIES)])
    d.polygon([(x0 - 30, y0), (x0 + bw + 30, y0), (x0 + bw // 2, y0 - 120)], fill=(120, 70, 60))
    cols = 4
    gap = bw // (cols + 1)
    for r in range(max(1, (bh - 160) // 150)):
        for c in range(cols):
            wx = x0 + gap * (c + 1) - 35
            wy = y0 + 40 + r * 150
            d.rectangle((wx, wy, wx + 70, wy + 100), fill=(150, 195, 230), outline=(90, 90, 90), width=4)
    d.rectangle((x0 + bw // 2 - 45, ground - 130, x0 + bw // 2 + 45, ground), fill=(100, 70, 50))
    img.save(OUT / f"sample_{idx + 1:02d}.jpg", quality=90)


if __name__ == "__main__":
    for i in range(6):
        draw_scene(i)
    print(f"Created 6 synthetic images in {OUT}")