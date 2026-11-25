"""Mockup only: overlays a simulated Projectivy clock + app dock on a wallpaper."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).resolve().parent.parent / "fonts"
src, dst = sys.argv[1], sys.argv[2]
img = Image.open(src).convert("RGB").resize((1920, 1080), Image.LANCZOS)
d = ImageDraw.Draw(img, "RGBA")
f = lambda n, s: ImageFont.truetype(str(FONTS / n), s)

# clock (Projectivy, two-line format)
t, day = "1:05", "WEDNESDAY 11/25"
ft, fd = f("InterDisplay-Light.otf", 84), f("Inter-SemiBold.otf", 20)
tw = d.textlength(t, font=ft)
d.text((1920 - 96 - tw, 38), t, font=ft, fill=(255, 255, 255, 245))
x = 1920 - 96
for ch in reversed(day):
    x -= d.textlength(ch, font=fd) + 3
d.text((0, 0), "", font=fd)
xx = x
for ch in day:
    d.text((xx, 140), ch, font=fd, fill=(255, 255, 255, 200))
    xx += d.textlength(ch, font=fd) + 3

# dock with app names (stand-ins for the real app icons)
apps = ["hulu", "KODI", "nuvio", "YouTube", "Apple TV", "Disney+", "prime video",
        "ESPN", "MLB", "NBA", "peacock"]
fa = f("Inter-Bold.otf", 22)
d.rounded_rectangle((70, 930, 1850, 1040), radius=22, fill=(255, 255, 255, 14))
slot = (1850 - 70) / len(apps)
for i, a in enumerate(apps):
    cx = 70 + slot * i + slot / 2
    if i == 0:
        d.rounded_rectangle((cx - 72, 945, cx + 72, 1025), radius=14,
                            outline=(255, 255, 255, 230), width=3, fill=(255, 255, 255, 30))
    w = d.textlength(a, font=fa)
    d.text((cx - w / 2, 972), a, font=fa, fill=(255, 255, 255, 235))
img.save(dst, quality=92)
