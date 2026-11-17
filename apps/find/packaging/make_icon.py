"""Regenerate the NOBAD Find app icon from the brand mark (run when the mark changes; needs Pillow):

    python packaging/make_icon.py

Reads nobadfind/ui/brand/nobad-mark.png and writes packaging/nobadfind.ico (16-256 px, for the exe, the installer
and the shortcuts). The .ico is committed, like the VPN's, so a build doesn't need Pillow.
"""
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "nobadfind", "ui", "brand", "nobad-mark.png")
OUT = os.path.join(HERE, "nobadfind.ico")
SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]


def main():
    mark = Image.open(SRC).convert("RGBA")
    if mark.width != mark.height:
        s = max(mark.size)
        sq = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        sq.paste(mark, ((s - mark.width) // 2, (s - mark.height) // 2), mark)
        mark = sq
    mark.save(OUT, sizes=SIZES)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
