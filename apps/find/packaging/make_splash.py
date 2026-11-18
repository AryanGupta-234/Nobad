"""Draw the start-up splash (run when the design changes; needs Pillow):

    python packaging/make_splash.py

480x270, the NOBAD mark on the app's dark background with the product name. The PyInstaller Splash in
nobadfind.spec shows it while the exe unpacks; app.py closes it when the window is up. Writes
nobadfind/ui/brand/splash.png (committed).
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
BRAND = os.path.join(HERE, "..", "nobadfind", "ui", "brand")
BG, ORANGE, TEXT, DIM = (7, 8, 10), (255, 77, 0), (243, 244, 246), (140, 145, 152)
FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


def font(names, size):
    for n in names:
        try:
            return ImageFont.truetype(os.path.join(FONTS, n), size)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    im = Image.new("RGB", (480, 270), BG)
    mark = Image.open(os.path.join(BRAND, "nobad-mark.png")).convert("RGBA").resize((112, 112), Image.LANCZOS)
    im.paste(mark, (52, 79), mark)
    d = ImageDraw.Draw(im)
    d.text((186, 96), "NOBAD", font=font(["ariblk.ttf", "arialbd.ttf"], 36), fill=TEXT)
    d.text((186, 136), "FIND", font=font(["ariblk.ttf", "arialbd.ttf"], 36), fill=ORANGE)
    d.rectangle((186, 186, 186 + 36, 188), fill=ORANGE)
    d.text((186, 198), "Private file search. Offline.", font=font(["consola.ttf", "cour.ttf"], 12), fill=DIM)
    d.rectangle((0, 0, 479, 269), outline=(32, 35, 40))
    out = os.path.join(BRAND, "splash.png")
    im.save(out, optimize=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
