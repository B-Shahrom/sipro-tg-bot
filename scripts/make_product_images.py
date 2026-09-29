"""Generate illustrated product cards for the sample catalog.

    pip install pillow
    python scripts/make_product_images.py                      # all products in data/catalog_sample.csv
    python scripts/make_product_images.py my_catalog.csv       # another catalog

Writes data/images/<SKU>.jpg. These are stylized placeholders so the demo catalog looks alive;
replace them with real product photos (same file name, or a URL in the image_url column).
"""

import csv
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "images"
SIZE = 800
SS = 2  # supersampling for smooth edges
W = SIZE * SS

FONT_DIRS = [
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("C:/Windows/Fonts"),
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
]
FONT_FILES = {"bold": ["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"],
              "regular": ["DejaVuSans.ttf", "arial.ttf", "Arial.ttf"]}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for d in FONT_DIRS:
        for name in FONT_FILES[kind]:
            if (d / name).exists():
                return ImageFont.truetype(str(d / name), size * SS)
    return ImageFont.load_default(size * SS)


# category -> (top color, bottom color, accent)
THEMES = {
    "Процессоры": ((24, 32, 64), (58, 82, 160), (255, 196, 64)),
    "Материнские платы": ((18, 40, 38), (32, 104, 92), (120, 255, 214)),
    "Оперативная память": ((44, 20, 64), (120, 56, 170), (255, 120, 220)),
    "Видеокарты": ((14, 18, 24), (40, 70, 60), (118, 255, 3)),
    "Накопители": ((20, 30, 50), (40, 110, 170), (120, 220, 255)),
    "Блоки питания": ((30, 30, 30), (90, 70, 40), (255, 170, 60)),
    "Корпуса": ((16, 16, 28), (70, 50, 120), (160, 120, 255)),
    "Охлаждение": ((10, 36, 60), (40, 140, 200), (170, 240, 255)),
    "Мониторы": ((20, 20, 36), (70, 40, 110), (255, 90, 160)),
    "Клавиатуры": ((30, 22, 40), (110, 60, 90), (255, 150, 90)),
    "Мыши и коврики": ((22, 30, 30), (60, 110, 100), (110, 255, 190)),
    "Гарнитуры и аудио": ((36, 16, 20), (140, 40, 60), (255, 120, 120)),
    "Веб-камеры и микрофоны": ((26, 26, 26), (80, 80, 110), (180, 200, 255)),
    "Сетевое оборудование": ((12, 30, 44), (30, 90, 120), (80, 220, 255)),
    "ИБП и сетевые фильтры": ((34, 30, 14), (120, 100, 30), (255, 230, 90)),
    "Готовые ПК": ((12, 12, 30), (40, 60, 140), (0, 220, 255)),
}
DEFAULT_THEME = ((24, 24, 32), (70, 70, 90), (200, 200, 255))

DARK = (32, 34, 40)
DARK2 = (48, 51, 60)
METAL = (170, 176, 186)
METAL_D = (120, 126, 136)
PCB = (22, 70, 52)
GOLD = (214, 172, 72)


def S(*v):
    """Scale 800-px design coordinates to the supersampled canvas."""
    return [int(x * SS) for x in v]


def parse_specs(specs: str) -> dict[str, str]:
    out = {}
    for part in specs.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def gradient(top, bottom) -> Image.Image:
    img = Image.new("RGB", (W, W), top)
    px = ImageDraw.Draw(img)
    for y in range(W):
        t = y / (W - 1)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        px.line([(0, y), (W, y)], fill=c)
    return img


def glow(img: Image.Image, xy, color, radius=260):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x, y = xy
    d.ellipse(S(x - radius, y - radius, x + radius, y + radius), fill=(*color, 70))
    layer = layer.filter(ImageFilter.GaussianBlur(90 * SS))
    img.paste(layer, (0, 0), layer)


def fan(d: ImageDraw.ImageDraw, cx, cy, r, accent=None, blades=7):
    d.ellipse(S(cx - r, cy - r, cx + r, cy + r), fill=(20, 22, 26), outline=accent or METAL_D, width=4 * SS)
    for i in range(blades):
        a = 2 * math.pi * i / blades
        pts = []
        for t, off in ((0.28, -0.25), (0.92, 0.05), (0.92, 0.35), (0.28, 0.2)):
            ang = a + off
            pts.append((cx + math.cos(ang) * r * t, cy + math.sin(ang) * r * t))
        d.polygon([tuple(S(*p)) for p in pts], fill=(58, 62, 72))
    d.ellipse(S(cx - r * 0.27, cy - r * 0.27, cx + r * 0.27, cy + r * 0.27), fill=(38, 40, 46), outline=METAL_D,
              width=2 * SS)


# ---------------------------------------------------------------- drawings (centered around 400, 330)

def draw_gpu(d, p, accent):
    fans = 3 if p["price"] >= 60000 else 2 if p["price"] >= 20000 else 1
    x0, x1 = 130, 690
    d.rounded_rectangle(S(x0, 205, x1, 440), 26 * SS, fill=DARK, outline=(70, 74, 84), width=3 * SS)
    d.rectangle(S(x0 - 26, 190, x0, 470), fill=METAL)                   # bracket
    for i in range(3):
        d.rectangle(S(x0 - 20, 220 + i * 60, x0 - 6, 255 + i * 60), fill=METAL_D)
    d.rectangle(S(x0 + 40, 440, x0 + 330, 458), fill=PCB)               # PCIe edge
    for i in range(24):
        d.rectangle(S(x0 + 46 + i * 12, 444, x0 + 52 + i * 12, 458), fill=GOLD)
    span = (x1 - x0 - 40) / fans
    r = min(span / 2 - 12, 100)
    for i in range(fans):
        fan(d, x0 + 20 + span * (i + 0.5), 322, r, accent)
    d.line(S(x0 + 20, 216, x1 - 20, 216), fill=accent, width=5 * SS)


def draw_cpu(d, p, accent):
    d.rounded_rectangle(S(230, 160, 570, 500), 20 * SS, fill=PCB)
    for i in range(14):
        for side in range(4):
            t = 175 + i * 23
            pos = {0: (t, 168), 1: (t, 486), 2: (238, t), 3: (556, t)}[side]
            d.rectangle(S(pos[0], pos[1], pos[0] + 6, pos[1] + 6), fill=GOLD)
    d.rounded_rectangle(S(265, 195, 535, 465), 26 * SS, fill=(196, 200, 208), outline=(230, 232, 236), width=4 * SS)
    brand = p["brand"].upper() if p["brand"] else "CPU"
    f = font("bold", 54)
    d.text(S(400, 300), brand, font=f, fill=(60, 64, 72), anchor="mm")
    socket = p["specs"].get("Сокет", "")
    d.text(S(400, 370), socket, font=font("regular", 30), fill=(90, 94, 104), anchor="mm")
    d.rectangle(S(265, 430, 535, 440), fill=accent)


def draw_mb(d, p, accent):
    ff = p["specs"].get("Форм-фактор", "ATX")
    h = 470 if ff == "ATX" else 400 if ff == "mATX" else 330
    x0, y0 = 400 - 180, 330 - h // 2
    d.rounded_rectangle(S(x0, y0, x0 + 360, y0 + h), 12 * SS, fill=(30, 36, 40), outline=(60, 70, 74), width=3 * SS)
    d.rectangle(S(x0 + 70, y0 + 50, x0 + 170, y0 + 150), fill=METAL, outline=(210, 214, 220), width=3 * SS)  # socket
    d.rectangle(S(x0 + 95, y0 + 75, x0 + 145, y0 + 125), fill=METAL_D)
    for i in range(4 if "4 слота" in p["specs"].get("Память", "4 слота") else 2):
        d.rectangle(S(x0 + 205 + i * 22, y0 + 30, x0 + 217 + i * 22, y0 + 190), fill=(80, 84, 94))
    d.rectangle(S(x0 + 10, y0 + 30, x0 + 55, y0 + 170), fill=DARK2)   # VRM heatsink
    d.rectangle(S(x0 + 70, y0 + 10, x0 + 190, y0 + 38), fill=DARK2)
    d.rectangle(S(x0 + 30, y0 + 215, x0 + 330, y0 + 232), fill=(90, 94, 104))  # PCIe x16
    d.rectangle(S(x0 + 30, y0 + 215, x0 + 330, y0 + 219), fill=accent)
    if h > 360:
        d.rectangle(S(x0 + 30, y0 + 290, x0 + 250, y0 + 300), fill=(70, 74, 84))
        d.rounded_rectangle(S(x0 + 240, y0 + h - 130, x0 + 330, y0 + h - 40), 8 * SS, fill=DARK2)  # chipset
    d.rectangle(S(x0 + 40, y0 + 250, x0 + 220, y0 + 266), fill=(60, 64, 72))  # M.2 heatsink


def draw_ram(d, p, accent):
    rgb = "RGB" in p["specs"] or "RGB" in p["name"]
    white = "бел" in p["specs"].get("Цвет", "") or "бел" in p["name"]
    body = (225, 228, 234) if white else DARK
    for dy in (0, 110):
        y = 230 + dy
        d.rounded_rectangle(S(140, y, 660, y + 90), 10 * SS, fill=body, outline=(90, 94, 104), width=3 * SS)
        d.rectangle(S(150, y + 90, 650, y + 104), fill=PCB)
        for k in range(40):
            d.rectangle(S(156 + k * 12, y + 94, 161 + k * 12, y + 104), fill=GOLD)
        if rgb:
            d.rectangle(S(140, y - 14, 660, y + 2), fill=accent)
        d.text(S(400, y + 45), p["specs"].get("Тип", "DDR"), font=font("bold", 30),
               fill=(60, 64, 72) if white else (200, 204, 212), anchor="mm")


def draw_storage(d, p, accent):
    kind = p["specs"].get("Тип", "")
    if "M.2" in kind:
        d.rounded_rectangle(S(120, 280, 680, 380), 8 * SS, fill=(18, 24, 30))
        for x in (190, 330, 460):
            d.rectangle(S(x, 298, x + 110, 362), fill=(40, 44, 52))
        d.rectangle(S(640, 300, 680, 360), fill=GOLD)
        d.ellipse(S(108, 318, 132, 342), fill=(90, 94, 104))
        d.rectangle(S(190, 298, 570, 330), fill=accent)
        d.text(S(380, 314), p["brand"], font=font("bold", 26), fill=(20, 24, 30), anchor="mm")
    elif "HDD" in kind:
        d.rounded_rectangle(S(230, 150, 570, 510), 18 * SS, fill=METAL, outline=(210, 214, 220), width=4 * SS)
        d.ellipse(S(270, 190, 530, 450), fill=(200, 204, 212), outline=METAL_D, width=4 * SS)
        d.ellipse(S(385, 305, 415, 335), fill=METAL_D)
        d.line(S(510, 460, 420, 330), fill=(60, 64, 72), width=12 * SS)
    else:
        d.rounded_rectangle(S(220, 190, 580, 470), 22 * SS, fill=DARK2, outline=(90, 94, 104), width=4 * SS)
        d.rectangle(S(220, 290, 580, 360), fill=accent)
        d.text(S(400, 325), p["brand"], font=font("bold", 36), fill=(20, 24, 30), anchor="mm")


def draw_psu(d, p, accent):
    d.rounded_rectangle(S(190, 170, 610, 480), 18 * SS, fill=DARK, outline=(80, 84, 94), width=4 * SS)
    for r in range(130, 20, -22):
        d.ellipse(S(400 - r, 325 - r, 400 + r, 325 + r), outline=(90, 94, 104), width=4 * SS)
    d.line(S(270, 325, 530, 325), fill=(90, 94, 104), width=4 * SS)
    d.line(S(400, 195, 400, 455), fill=(90, 94, 104), width=4 * SS)
    watts = p["specs"].get("Мощность", "").replace(" ", "")
    d.rounded_rectangle(S(470, 430, 600, 470), 10 * SS, fill=accent)
    d.text(S(535, 450), watts, font=font("bold", 24), fill=(20, 20, 20), anchor="mm")


def draw_case(d, p, accent):
    white = "бел" in p["specs"].get("Цвет", "")
    body = (230, 232, 238) if white else DARK
    itx = "Mini-ITX" == p["specs"].get("Форм-факторы плат", "")
    top, bottom = (190, 470) if itx else (120, 520)
    left, right = (230, 570) if itx else (260, 540)
    d.rounded_rectangle(S(left, top, right, bottom), 20 * SS, fill=body, outline=(90, 94, 104), width=4 * SS)
    d.rounded_rectangle(S(left + 25, top + 25, right - 25, bottom - 25), 12 * SS, fill=(40, 44, 60))
    n = 2 if itx else 3
    step = (bottom - top - 60) / n
    for i in range(n):
        cy = top + 30 + step * (i + 0.5)
        fan(d, right - 75, cy, min(48, step / 2 - 6), accent)
    d.rectangle(S(left + 45, top + 60, left + 170, top + 200), fill=(24, 60, 44))
    d.rectangle(S(left + 45, top + 230, right - 120, top + 260), fill=(70, 74, 84))


def draw_cooler(d, p, accent):
    kind = p["specs"].get("Тип", "")
    if "термопаст" in kind:
        d.rounded_rectangle(S(250, 290, 520, 360), 30 * SS, fill=(210, 214, 220))
        d.polygon([tuple(S(*pt)) for pt in ((520, 300), (600, 318), (600, 332), (520, 350))], fill=(180, 184, 190))
        d.rectangle(S(190, 305, 250, 345), fill=accent)
        return
    if "СЖО" in kind:
        rad = int("".join(ch for ch in p["specs"].get("Радиатор", "240") if ch.isdigit()) or 240)
        fans = 3 if rad >= 360 else 2
        width = fans * 150 + 20
        x0 = 400 - width // 2
        d.rounded_rectangle(S(x0, 170, x0 + width, 330), 12 * SS, fill=DARK, outline=(80, 84, 94), width=3 * SS)
        for i in range(fans):
            fan(d, x0 + 85 + i * 150, 250, 66, accent)
        d.line(S(x0 + 60, 330, 330, 430), fill=(40, 42, 48), width=18 * SS)
        d.line(S(x0 + 100, 330, 360, 430), fill=(40, 42, 48), width=18 * SS)
        d.ellipse(S(300, 400, 440, 510), fill=DARK2, outline=accent, width=6 * SS)
        return
    towers = 2 if "2 башни" in kind else 1
    for t in range(towers):
        x = 300 + t * 120 if towers == 2 else 330
        for i in range(22):
            d.rectangle(S(x, 150 + i * 14, x + 110, 158 + i * 14), fill=METAL)
    for i in range(4):
        d.line(S(345 + i * 30, 460, 345 + i * 30, 150), fill=(190, 120, 70), width=8 * SS)
    d.rounded_rectangle(S(305, 470, 495, 505), 6 * SS, fill=METAL_D)
    fan(d, 250 if towers == 1 else 240, 320, 110, accent)


def draw_monitor(d, p, accent):
    diag = p["specs"].get("Диагональ", "24")
    ultrawide = diag.startswith("34")
    wdt = 560 if ultrawide else 480 if diag.startswith("27") else 430
    hgt = int(wdt / (2.4 if ultrawide else 1.78))
    x0, y0 = 400 - wdt // 2, 290 - hgt // 2
    d.rounded_rectangle(S(x0 - 12, y0 - 12, x0 + wdt + 12, y0 + hgt + 12), 14 * SS, fill=(18, 18, 22))
    screen = Image.new("RGB", (wdt * SS, hgt * SS))
    sd = ImageDraw.Draw(screen)
    for y in range(hgt * SS):
        t = y / (hgt * SS)
        sd.line([(0, y), (wdt * SS, y)], fill=(int(40 + 120 * t), int(20 + 40 * t), int(90 + 100 * (1 - t))))
    sd.polygon([(0, hgt * SS), (wdt * SS * 0.45, hgt * SS * 0.45), (wdt * SS * 0.8, hgt * SS)], fill=(20, 16, 40))
    sd.polygon([(wdt * SS * 0.3, hgt * SS), (wdt * SS * 0.7, hgt * SS * 0.3), (wdt * SS, hgt * SS)], fill=(30, 22, 60))
    sd.ellipse([wdt * SS * 0.62, hgt * SS * 0.12, wdt * SS * 0.74, hgt * SS * 0.12 + wdt * SS * 0.12], fill=accent)
    d._image.paste(screen, tuple(S(x0, y0)))
    d.rectangle(S(385, y0 + hgt + 12, 415, 470), fill=(60, 62, 70))
    d.rounded_rectangle(S(300, 465, 500, 490), 10 * SS, fill=(60, 62, 70))
    hz = p["specs"].get("Частота", "")
    if hz:
        d.rounded_rectangle(S(x0 + wdt - 150, y0 + 14, x0 + wdt - 14, y0 + 58), 10 * SS, fill=accent)
        d.text(S(x0 + wdt - 82, y0 + 36), hz, font=font("bold", 24), fill=(20, 20, 20), anchor="mm")


def draw_keyboard(d, p, accent):
    if "комплект" in p["specs"].get("Тип", ""):
        draw_mouse(d, p, accent, x_shift=210, small=True)
    tkl = "75%" in p["specs"].get("Тип", "") or "TKL" in p["specs"].get("Тип", "")
    x0, x1 = (140, 600) if tkl else (100, 640)
    if "комплект" in p["specs"].get("Тип", ""):
        x0, x1 = 90, 520
    d.rounded_rectangle(S(x0, 230, x1, 430), 20 * SS, fill=DARK, outline=(80, 84, 94), width=3 * SS)
    cols = int((x1 - x0 - 30) / 34)
    rgb = "RGB" in p["specs"]
    for r in range(5):
        for c in range(cols):
            x = x0 + 18 + c * 34
            y = 248 + r * 35
            color = accent if rgb and (r + c) % 7 == 0 else (70, 74, 84)
            d.rounded_rectangle(S(x, y, x + 28, y + 28), 5 * SS, fill=color)


def draw_mouse(d, p, accent, x_shift=0, small=False):
    kind = p["specs"].get("Тип", "")
    if "коврик" in kind:
        d.rounded_rectangle(S(100, 220, 700, 460), 24 * SS, fill=(26, 28, 34), outline=accent, width=6 * SS)
        d.text(S(400, 340), "XL", font=font("bold", 90), fill=(50, 54, 64), anchor="mm")
        return
    s = 0.55 if small else 1.0
    cx = 400 + x_shift
    w, h = 170 * s, 280 * s
    d.ellipse(S(cx - w / 2, 330 - h / 2, cx + w / 2, 330 + h / 2), fill=DARK, outline=(90, 94, 104), width=4 * SS)
    d.line(S(cx, 330 - h / 2 + 10, cx, 330 - h * 0.08), fill=(90, 94, 104), width=4 * SS)
    d.rounded_rectangle(S(cx - 10 * s, 330 - h * 0.34, cx + 10 * s, 330 - h * 0.18), 6 * SS, fill=accent)
    if not small and "беспровод" not in kind:
        d.line(S(cx, 330 - h / 2, cx, 150), fill=(60, 62, 70), width=6 * SS)


def draw_audio(d, p, accent):
    kind = p["specs"].get("Тип", "")
    if "колонки" in kind:
        for x in (190, 450):
            d.rounded_rectangle(S(x, 170, x + 160, 480), 16 * SS, fill=DARK, outline=(80, 84, 94), width=3 * SS)
            d.ellipse(S(x + 25, 300, x + 135, 410), fill=(20, 22, 26), outline=accent, width=5 * SS)
            d.ellipse(S(x + 55, 200, x + 105, 250), fill=(20, 22, 26), outline=METAL_D, width=3 * SS)
        return
    d.arc(S(230, 150, 570, 470), 180, 360, fill=DARK2, width=34 * SS)
    for x in (205, 505):
        d.rounded_rectangle(S(x, 280, x + 90, 450), 40 * SS, fill=DARK, outline=accent, width=5 * SS)
    if "Микрофон" in p["specs"]:
        d.line(S(250, 430, 330, 500), fill=DARK2, width=12 * SS)
        d.ellipse(S(318, 488, 348, 518), fill=accent)


def draw_cam(d, p, accent):
    if "микрофон" in p["specs"].get("Тип", ""):
        d.rounded_rectangle(S(340, 140, 460, 380), 60 * SS, fill=DARK2, outline=METAL_D, width=4 * SS)
        for i in range(8):
            d.line(S(355, 170 + i * 24, 445, 170 + i * 24), fill=(90, 94, 104), width=3 * SS)
        d.rectangle(S(390, 380, 410, 470), fill=METAL_D)
        d.rounded_rectangle(S(300, 465, 500, 495), 12 * SS, fill=DARK)
        d.ellipse(S(392, 400, 408, 416), fill=accent)
        return
    d.rounded_rectangle(S(230, 230, 570, 370), 60 * SS, fill=DARK, outline=(80, 84, 94), width=3 * SS)
    d.ellipse(S(345, 245, 455, 355), fill=(14, 14, 18), outline=METAL, width=6 * SS)
    d.ellipse(S(375, 275, 425, 325), fill=(30, 50, 90))
    d.ellipse(S(390, 285, 404, 299), fill=(200, 220, 255))
    d.ellipse(S(500, 290, 514, 304), fill=accent)
    d.polygon([tuple(S(*pt)) for pt in ((360, 370), (440, 370), (470, 470), (330, 470))], fill=DARK2)


def draw_network(d, p, accent):
    kind = p["specs"].get("Тип", "")
    if "роутер" in kind:
        d.rounded_rectangle(S(180, 330, 620, 430), 20 * SS, fill=DARK, outline=(80, 84, 94), width=3 * SS)
        for x in (220, 330, 470, 580):
            d.rounded_rectangle(S(x - 10, 150, x + 10, 340), 8 * SS, fill=DARK2)
        for i in range(6):
            d.ellipse(S(240 + i * 40, 372, 254 + i * 40, 386), fill=accent)
    elif "кабель" in kind:
        for i in range(5):
            d.arc(S(220 + i * 12, 180 + i * 12, 580 - i * 12, 480 - i * 12), 0, 330, fill=accent, width=10 * SS)
        d.rounded_rectangle(S(560, 300, 640, 350), 8 * SS, fill=(200, 210, 220))
    else:
        d.rounded_rectangle(S(240, 290, 520, 370), 16 * SS, fill=DARK, outline=(80, 84, 94), width=3 * SS)
        d.rectangle(S(520, 305, 580, 355), fill=METAL)
        for x in (300, 380, 460) if "PCIe" in kind else (330, 430):
            d.rounded_rectangle(S(x - 8, 150, x + 8, 295), 6 * SS, fill=DARK2)
        d.ellipse(S(270, 322, 284, 336), fill=accent)


def draw_ups(d, p, accent):
    if "фильтр" in p["specs"].get("Тип", ""):
        d.rounded_rectangle(S(120, 290, 680, 380), 20 * SS, fill=(230, 232, 236), outline=(160, 164, 172), width=3 * SS)
        for i in range(5):
            d.ellipse(S(200 + i * 90, 305, 260 + i * 90, 365), fill=(200, 204, 210), outline=(150, 154, 160), width=3 * SS)
        d.rounded_rectangle(S(140, 318, 176, 352), 6 * SS, fill=(220, 40, 40))
        return
    d.rounded_rectangle(S(260, 150, 540, 500), 20 * SS, fill=DARK, outline=(80, 84, 94), width=3 * SS)
    d.rounded_rectangle(S(300, 200, 500, 280), 8 * SS, fill=(20, 40, 30))
    d.text(S(400, 240), "230V", font=font("bold", 34), fill=accent, anchor="mm")
    d.ellipse(S(375, 320, 425, 370), fill=DARK2, outline=accent, width=5 * SS)
    for i in range(3):
        d.rectangle(S(310 + i * 70, 420, 340 + i * 70, 440), fill=(70, 74, 84))


def draw_pc(d, p, accent):
    d.rounded_rectangle(S(130, 190, 460, 420), 12 * SS, fill=(18, 18, 22))
    d.rectangle(S(145, 205, 445, 405), fill=(40, 30, 90))
    d.polygon([tuple(S(*pt)) for pt in ((145, 405), (300, 290), (445, 405))], fill=(24, 20, 60))
    d.rectangle(S(280, 420, 300, 470), fill=(60, 62, 70))
    d.rounded_rectangle(S(220, 465, 360, 485), 8 * SS, fill=(60, 62, 70))
    d.rounded_rectangle(S(430, 130, 660, 510), 18 * SS, fill=DARK, outline=(90, 94, 104), width=4 * SS)
    d.rounded_rectangle(S(450, 150, 640, 490), 10 * SS, fill=(36, 40, 58))
    gaming = "игр" in p["specs"].get("Назначение", "")
    for i in range(3 if gaming else 2):
        fan(d, 590, 200 + i * 100, 42, accent if gaming else METAL_D)
    if gaming:
        d.rectangle(S(460, 360, 570, 385), fill=(70, 74, 84))
        d.rectangle(S(460, 360, 570, 364), fill=accent)


DRAWERS = {
    "Процессоры": draw_cpu, "Материнские платы": draw_mb, "Оперативная память": draw_ram,
    "Видеокарты": draw_gpu, "Накопители": draw_storage, "Блоки питания": draw_psu, "Корпуса": draw_case,
    "Охлаждение": draw_cooler, "Мониторы": draw_monitor, "Клавиатуры": draw_keyboard, "Мыши и коврики": draw_mouse,
    "Гарнитуры и аудио": draw_audio, "Веб-камеры и микрофоны": draw_cam, "Сетевое оборудование": draw_network,
    "ИБП и сетевые фильтры": draw_ups, "Готовые ПК": draw_pc,
}

CHIP_KEYS = {
    "Процессоры": ["Сокет", "Ядра/потоки"], "Материнские платы": ["Сокет", "Форм-фактор"],
    "Оперативная память": ["Объём", "Частота"], "Видеокарты": ["Видеопамять"], "Накопители": ["Объём"],
    "Блоки питания": ["Мощность", "Сертификат"], "Корпуса": ["Цвет"], "Охлаждение": ["TDP"],
    "Мониторы": ["Диагональ", "Разрешение"], "Готовые ПК": ["ОЗУ", "SSD"],
}


def wrap(text: str, f, max_w: int, draw: ImageDraw.ImageDraw, max_lines=2) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        cand = f"{cur} {word}".strip()
        if draw.textlength(cand, font=f) <= max_w:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while draw.textlength(lines[-1] + "…", font=f) > max_w:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def render(row: dict) -> Image.Image:
    cat = row["category"]
    top, bottom, accent = THEMES.get(cat, DEFAULT_THEME)
    p = {"name": row["name"], "brand": row.get("brand", ""), "price": float(row["price"]),
         "specs": parse_specs(row.get("specs", ""))}
    img = gradient(top, bottom)
    glow(img, (400, 320), accent)
    d = ImageDraw.Draw(img)
    DRAWERS.get(cat, draw_pc)(d, p, accent)

    # store badge
    d.rounded_rectangle(S(28, 28, 168, 76), 24 * SS, fill=(0, 0, 0))
    d.text(S(98, 52), "SIPRO", font=font("bold", 26), fill=accent, anchor="mm")

    # info panel
    d.rounded_rectangle(S(24, 560, 776, 776), 28 * SS, fill=(250, 250, 252))
    if p["brand"]:
        d.text(S(52, 596), p["brand"].upper(), font=font("bold", 22), fill=tuple(int(c * 0.6) for c in bottom),
               anchor="lm")
    f = font("bold", 34)
    for i, line in enumerate(wrap(row["name"], f, 700 * SS, d)):
        d.text(S(52, 640 + i * 44), line, font=f, fill=(24, 26, 32), anchor="lm")
    chips = [p["specs"][k].split(";")[0][:22] for k in CHIP_KEYS.get(cat, []) if p["specs"].get(k)]
    x = 52
    fc = font("regular", 22)
    for chip in chips:
        w = d.textlength(chip, font=fc) / SS + 28
        d.rounded_rectangle(S(x, 728, x + w, 762), 17 * SS, fill=(236, 238, 244))
        d.text(S(x + w / 2, 745), chip, font=fc, fill=(60, 64, 76), anchor="mm")
        x += w + 10
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "catalog_sample.csv"
    OUT.mkdir(parents=True, exist_ok=True)
    with open(src, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        render(row).save(OUT / f"{row['sku']}.jpg", quality=86, optimize=True)
    print(f"{len(rows)} images -> {OUT}")


if __name__ == "__main__":
    main()
