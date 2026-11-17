"""Draw the NOBAD Find app icon (run when the design changes; needs Pillow):

    python packaging/make_icon.py

The NOBAD brand mark (nobadfind/ui/brand/nobad-mark.png) stays the brand inside the app. The app icon (the exe,
the taskbar, the installer and the shortcuts) is NOBAD Find's own: the NOBAD black tile and orange, with a
magnifying glass whose lens holds the NOBAD "n". Writes packaging/nobadfind.ico (16-256 px) and
packaging/nobadfind-icon.png (512 px, for previews). The .ico is committed, so a build doesn't need Pillow.
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "nobadfind.ico")
PNG = os.path.join(HERE, "nobadfind-icon.png")
SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]
ORANGE = (255, 77, 0, 255)
TILE = (10, 11, 13, 255)
RIM = (40, 44, 52, 255)


def _font(px):
    for name in ("ariblk.ttf", "seguibl.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def draw(size=1024, simple=False):
    """simple: the 16-24 px version (no letter in the lens: it would be a blur)."""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = size / 1024
    d.rounded_rectangle([24 * s, 24 * s, 1000 * s, 1000 * s], radius=220 * s, fill=TILE, outline=RIM,
                        width=max(1, int(10 * s)))
    cx, cy, r = 440 * s, 430 * s, 255 * s
    ring = (78 if simple else 64) * s
    # handle first, so the ring sits on top of it
    d.line([(cx + r * 0.62, cy + r * 0.62), (850 * s, 840 * s)], fill=ORANGE, width=int((150 if simple else 130) * s))
    d.ellipse([838 * s - 75 * s, 828 * s - 75 * s, 862 * s + 50 * s, 852 * s + 50 * s], fill=ORANGE)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ORANGE, width=int(ring))
    if not simple:
        f = _font(int(300 * s))
        box = d.textbbox((0, 0), "n", font=f)
        w, h = box[2] - box[0], box[3] - box[1]
        d.text((cx - w / 2 - box[0], cy - h / 2 - box[1] - 6 * s), "n", font=f, fill=(243, 244, 246, 255))
    return im


def main():
    big, small = draw(1024), draw(1024, simple=True)
    frames = [(small if w <= 24 else big).resize((w, h), Image.LANCZOS) for w, h in SIZES]
    frames[-1].save(OUT, format="ICO", sizes=SIZES, append_images=frames[:-1])
    big.resize((512, 512), Image.LANCZOS).save(PNG)
    print("wrote", OUT, "and", PNG)


if __name__ == "__main__":
    main()
