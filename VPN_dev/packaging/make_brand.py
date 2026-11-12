"""Regenerate the app's brand files from the platform's logo assets (run when the logo changes):

    python packaging/make_brand.py [path/to/assets]      (default: ../assets next to VPN_dev)

Writes into nobadvpn/ui/brand/:
  nobad-logo.png, nobad-logo-light.png  copies of the wordmarks (dark / light lettering)
  nobad-mark.png                        512 px square "n" mark (tray icon, window icon)
  nobad.ico                             16-256 px multi-size app icon (exe, installer, shortcuts)
  splash.png                            880 x 520 startup splash (2x; scaled down at runtime)
"""
import os
import shutil
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(ROOT), "assets")
OUT = os.path.join(ROOT, "nobadvpn", "ui", "brand")
ORANGE = (246, 80, 0)
CARD = (11, 12, 16)


def font(size, bold=False):
    for name in (("segoeuib.ttf", "seguisb.ttf") if bold else ("segoeui.ttf",)) + ("arial.ttf", "DejaVuSans.ttf"):
        for d in (os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"), "/usr/share/fonts/truetype/dejavu"):
            p = os.path.join(d, name)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def trim(img):
    bbox = img.getchannel("A").point(lambda a: 255 if a > 12 else 0).getbbox()
    return img.crop(bbox) if bbox else img


def make_mark(logo):
    """The rotated black tile with the orange n: the left part of the dark wordmark."""
    mark = trim(logo.crop((0, 0, int(logo.width * 0.37), logo.height)))
    s = int(max(mark.size) * 1.06)
    sq = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sq.paste(mark, ((s - mark.width) // 2, (s - mark.height) // 2), mark)
    return sq.resize((512, 512), Image.LANCZOS)


def make_splash(light_logo):
    W, H, M, R = 880, 520, 28, 40               # canvas, shadow margin, corner radius
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # soft drop shadow
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((M, M + 10, W - M, H - M + 10), R, fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(16)))
    # card with an orange glow in the top-left corner (clipped to the card)
    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle((M, M, W - M, H - M), R, fill=CARD + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-180, -260, 520, 300), fill=ORANGE + (70,))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    mask = card.getchannel("A")
    card = Image.alpha_composite(card, Image.composite(glow, Image.new("RGBA", (W, H)), mask))
    ImageDraw.Draw(card).rounded_rectangle((M, M, W - M, H - M), R, outline=(255, 255, 255, 22), width=2)
    img = Image.alpha_composite(img, card)
    d = ImageDraw.Draw(img)
    # wordmark
    wm = trim(light_logo)
    tw = 430
    wm = wm.resize((tw, round(wm.height * tw / wm.width)), Image.LANCZOS)
    wx, wy = (W - wm.width) // 2 - 34, 150
    img.alpha_composite(wm, (wx, wy))
    # VPN pill to the right of the wordmark baseline
    f = font(30, bold=True)
    label = "VPN"
    lw = d.textlength(label, font=f) + 8 * 2  # letter-spaced below
    px, py = wx + wm.width + 22, wy + wm.height - 58
    pill = Image.new("RGBA", (W, H), (0, 0, 0, 0))   # blend onto the card (drawing directly would punch a hole)
    ImageDraw.Draw(pill).rounded_rectangle((px, py, px + lw + 26, py + 48), 24, fill=ORANGE + (40,),
                                           outline=ORANGE + (120,), width=2)
    img = Image.alpha_composite(img, pill)
    d = ImageDraw.Draw(img)
    cx = px + 13
    for ch in label:
        d.text((cx, py + 6), ch, font=f, fill=ORANGE + (255,))
        cx += d.textlength(ch, font=f) + 8
    # status line + accent bar
    f2 = font(26)
    msg = "Starting secure connection..."
    d.text(((W - d.textlength(msg, font=f2)) / 2, 352), msg, font=f2, fill=(150, 158, 176, 255))
    d.rounded_rectangle((W / 2 - 70, 408, W / 2 + 70, 414), 3, fill=ORANGE + (255,))
    # small "made with AI" signature: muted, letter-spaced, with a drawn four-point sparkle (no glyph needed)
    f3 = font(15, bold=True)
    tag = "MADE WITH AI"
    spacing = 3
    tw2 = sum(d.textlength(ch, font=f3) + spacing for ch in tag) - spacing
    total = 14 + 8 + tw2
    x0, y0 = (W - total) / 2, 446
    chip = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(chip).rounded_rectangle((x0 - 14, y0 - 7, x0 + total + 14, y0 + 23), 15,
                                           fill=(255, 255, 255, 10), outline=(255, 255, 255, 34), width=1)
    img = Image.alpha_composite(img, chip)
    d = ImageDraw.Draw(img)
    sx, sy, r = x0 + 7, y0 + 8, 7
    d.polygon([(sx, sy - r), (sx + 2, sy - 2), (sx + r, sy), (sx + 2, sy + 2), (sx, sy + r), (sx - 2, sy + 2),
               (sx - r, sy), (sx - 2, sy - 2)], fill=ORANGE + (230,))
    cx2 = x0 + 22
    for ch in tag:
        d.text((cx2, y0 - 1), ch, font=f3, fill=(176, 182, 198, 235))
        cx2 += d.textlength(ch, font=f3) + spacing
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    dark = Image.open(os.path.join(ASSETS, "nobad-logo.png")).convert("RGBA")
    light = Image.open(os.path.join(ASSETS, "nobad-logo-light.png")).convert("RGBA")
    for fn in ("nobad-logo.png", "nobad-logo-light.png"):
        shutil.copyfile(os.path.join(ASSETS, fn), os.path.join(OUT, fn))
    mark = make_mark(dark)
    mark.save(os.path.join(OUT, "nobad-mark.png"))
    mark.save(os.path.join(OUT, "nobad.ico"),
              sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    make_splash(light).save(os.path.join(OUT, "splash.png"), optimize=True)
    print("brand files written to", OUT)


if __name__ == "__main__":
    main()
