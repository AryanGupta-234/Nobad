"""Draw the NOBAD Find app icon (run when the design changes; needs Pillow):

    python packaging/make_icon.py

Every NOBAD app uses the company mark (the black tile with the "n", nobadfind/ui/brand/nobad-mark.png); only the
colour of the "n" changes per product. NOBAD VPN is orange, NOBAD File Bridge blue, NOBAD Find yellow.
This recolours the orange "n" of the mark, keeping its anti-aliased edges (each pixel is the orange times a
brightness, so it becomes the yellow times the same brightness).
Writes packaging/nobadfind.ico (16-256 px) and packaging/nobadfind-icon.png (512 px). Both are committed.
"""
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = os.path.join(HERE, "..", "nobadfind", "ui", "brand", "nobad-mark.png")
OUT = os.path.join(HERE, "nobadfind.ico")
PNG = os.path.join(HERE, "nobadfind-icon.png")
SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]
ORANGE = (248, 80, 1)                                  # the mark's "n"
YELLOW = (255, 196, 0)                                 # NOBAD Find


def recolour(px):
    r, g, b, a = px
    if r < 8 or g > r * 0.5 or b > r * 0.2:           # black tile, light rim and anything not orange stay
        return px
    t = min(1.0, r / ORANGE[0])
    return (round(YELLOW[0] * t), round(YELLOW[1] * t), round(YELLOW[2] * t), a)


def draw():
    im = Image.open(MARK).convert("RGBA")
    im.putdata([recolour(p) for p in im.getdata()])
    return im


def main():
    big = draw()
    frames = [big.resize(s, Image.LANCZOS) for s in SIZES]
    frames[-1].save(OUT, format="ICO", sizes=SIZES, append_images=frames[:-1])
    big.resize((512, 512), Image.LANCZOS).save(PNG)
    print("wrote", OUT, "and", PNG)


if __name__ == "__main__":
    main()
