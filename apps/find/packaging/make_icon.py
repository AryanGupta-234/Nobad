"""Draw the NOBAD Find app icon (run when the design changes; needs Pillow):

    python packaging/make_icon.py

The NOBAD brand mark (nobadfind/ui/brand/nobad-mark.png) stays the brand inside the app. The app icon (exe,
taskbar, title bar, installer, shortcuts) is NOBAD Find's own: a NOBAD-orange tile with a white magnifier and a
spark in the lens (search by meaning). At 16-24 px the spark is left out (it would only be a dot).
Writes packaging/nobadfind.ico (16-256 px) and packaging/nobadfind-icon.png (512 px). The .ico is committed.
"""
import math
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "nobadfind.ico")
PNG = os.path.join(HERE, "nobadfind-icon.png")
SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]
LIGHT, DEEP = (255, 106, 26), (226, 52, 0)            # NOBAD orange, top to bottom
WHITE = (255, 255, 255)


def _tile(size):
    g = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(g)
    for y in range(size):
        t = y / size
        d.line([(0, y), (size, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(LIGHT, DEEP)))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(g, (0, 0), mask)
    return out


def draw(size=1024, spark=True):
    im = _tile(size)
    d = ImageDraw.Draw(im)
    cx = cy = size * 0.43
    r, ring, handle = size * 0.20, size * 0.085, size * 0.20
    k = math.sqrt(0.5)
    x0, y0 = cx + (r + ring * 0.3) * k, cy + (r + ring * 0.3) * k
    x1, y1 = x0 + handle * k, y0 + handle * k
    d.line([(x0, y0), (x1, y1)], fill=WHITE, width=int(ring * 1.25))
    w = ring * 1.25 / 2
    d.ellipse([x1 - w, y1 - w, x1 + w, y1 + w], fill=WHITE)
    d.ellipse([cx - r - ring / 2, cy - r - ring / 2, cx + r + ring / 2, cy + r + ring / 2], outline=WHITE,
              width=int(ring))
    if spark:                                          # a four-point spark: search by meaning
        sr = size * 0.105
        pts = [(cx + (sr if i % 2 == 0 else sr * 0.28) * math.cos(math.pi / 4 * i - math.pi / 2),
                cy + (sr if i % 2 == 0 else sr * 0.28) * math.sin(math.pi / 4 * i - math.pi / 2)) for i in range(8)]
        d.polygon(pts, fill=WHITE)
    return im


def main():
    big, small = draw(1024), draw(1024, spark=False)
    frames = [(small if w <= 24 else big).resize((w, h), Image.LANCZOS) for w, h in SIZES]
    frames[-1].save(OUT, format="ICO", sizes=SIZES, append_images=frames[:-1])
    big.resize((512, 512), Image.LANCZOS).save(PNG)
    print("wrote", OUT, "and", PNG)


if __name__ == "__main__":
    main()
