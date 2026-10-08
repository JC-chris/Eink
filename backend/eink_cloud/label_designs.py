"""Uitgesproken labelontwerpen: andere lettertypes, prijs met verhoogde centen en grafische elementen.

Gemaakt voor e-paper: alleen volle vlakken en scherpe lijnen (geen grijstinten, geen anti-aliasing),
en per kleur een terugval naar zwart zodat elk ontwerp op elk display werkt.

Lettertypes (in `fonts/`, SIL Open Font License): Inter / Inter Display voor prijzen en moderne
tekst, Caladea voor een warme, ambachtelijke schreefletter.
"""

import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .displays import BLACK, BLUE, GREEN, RED, WHITE, YELLOW, DisplayType
from .render import LabelContent, format_euro

FONT_DIR = Path(__file__).parent / "fonts"
FONTS = {
    "price": "InterDisplay-Black.otf",
    "price_xb": "InterDisplay-ExtraBold.otf",
    "sans": "Inter-Regular.otf",
    "sans_semi": "Inter-SemiBold.otf",
    "sans_bold": "Inter-Bold.otf",
    "serif_bold": "Caladea-Bold.ttf",
    "serif_italic": "Caladea-Italic.ttf",
    "serif_bold_italic": "Caladea-BoldItalic.ttf",
}


@lru_cache(maxsize=512)
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / FONTS[name]), max(int(size), 7))


def fit(d: ImageDraw.ImageDraw, text: str, max_w: float, size: int, name: str) -> ImageFont.FreeTypeFont:
    size = int(size)
    while size > 7 and d.textlength(text, font=font(name, size)) > max_w:
        size -= 1
    return font(name, size)


def fit_line(d, text: str, max_w: float, size: int, name: str) -> tuple[ImageFont.FreeTypeFont, str]:
    f = fit(d, text, max_w, size, name)
    if d.textlength(text, font=f) <= max_w:
        return f, text
    while text and d.textlength(text + "…", font=f) > max_w:
        text = text[:-1]
    return f, text.rstrip() + "…"


def wrap(d, text: str, max_w: float, f: ImageFont.FreeTypeFont, max_lines: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for i, word in enumerate(words):
        cand = f"{line} {word}".strip()
        if d.textlength(cand, font=f) <= max_w:
            line = cand
            continue
        if line:
            lines.append(line)
        line = word
        if len(lines) == max_lines:
            break
    if line and len(lines) < max_lines:
        lines.append(line)
    if lines and " ".join(lines) != " ".join(words):
        last = lines[-1]
        while last and d.textlength(last + "…", font=f) > max_w:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def fit_wrapped(d, text: str, max_w: float, size: int, name: str, max_lines: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Grootste letter waarbij de tekst in max_lines regels past zonder dat een woord uitsteekt."""
    size = int(size)
    while True:
        f = font(name, size)
        lines = wrap(d, text, max_w, f, max_lines)
        fits = all(d.textlength(line, font=f) <= max_w for line in lines) and not lines[-1].endswith("…")
        if fits or size <= 8:
            break
        size -= 1
    # op de kleinste maat: regels die nog uitsteken hard inkorten
    out = []
    for line in lines:
        while line and d.textlength(line, font=f) > max_w:
            line = line[:-2] + "…"
        out.append(line)
    return f, out


# --- kleuren en canvas ---------------------------------------------------------------------------


def canvas(display: DisplayType, bg=WHITE) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (display.width, display.height), bg)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    return img, d


def pick(display: DisplayType, *colors) -> tuple[int, int, int]:
    return next((c for c in colors if c in display.palette), BLACK)


def on(color) -> tuple[int, int, int]:
    return BLACK if color in (WHITE, YELLOW) else WHITE


# --- prijs met verhoogde centen ------------------------------------------------------------------


def price(d: ImageDraw.ImageDraw, c: LabelContent, right: float, baseline: float, max_w: float, size: int,
          color=BLACK, unit_color=None, center_x: float | None = None, name: str = "price") -> tuple[float, float]:
    """€ 29⁹⁵/kg zoals in de winkel: kleine euro, grote euro's, verhoogde centen met de eenheid eronder.

    Geeft (bovenkant cijfers, breedte) terug.
    """
    euros, cents = divmod(c.price_cents, 100)
    whole, frac = f"{euros:,}".replace(",", "."), f"{cents:02d}"
    unit = f"/{c.unit}" if c.unit != "st" else ""
    size = int(size)
    while True:
        F, Fc, Fe = font(name, size), font(name, size * 0.5), font("price_xb", size * 0.4)
        Fu = font("sans_semi", max(8, size * 0.24))
        gap = max(1, size // 16)
        ww, wc, we = d.textlength(whole, font=F), d.textlength(frac, font=Fc), d.textlength("€", font=Fe)
        wu = d.textlength(unit, font=Fu) if unit else 0
        total = we + gap + ww + gap + max(wc, wu)
        if total <= max_w or size <= 10:
            break
        size -= 1
    if center_x is not None:
        right = center_x + total / 2
    x = right - total
    top = d.textbbox((0, baseline), whole, font=F, anchor="ls")[1]
    eb = d.textbbox((0, 0), "€", font=Fe, anchor="ls")
    d.text((x, top - eb[1]), "€", font=Fe, fill=color, anchor="ls")
    x += we + gap
    d.text((x, baseline), whole, font=F, fill=color, anchor="ls")
    x += ww + gap
    cb = d.textbbox((0, 0), frac, font=Fc, anchor="ls")
    d.text((x, top - cb[1]), frac, font=Fc, fill=color, anchor="ls")
    if unit:
        d.text((x, baseline), unit, font=Fu, fill=unit_color or color, anchor="ls")
    return top, total


def unit_price(d, c: LabelContent, x: float, baseline: float, max_w: float, size: int, color=BLACK,
               anchor: str = "ls", name: str = "sans") -> None:
    if c.unit_price_cents is not None:
        text = f"{format_euro(c.unit_price_cents)} per {c.unit_price_unit}"
        f, text = fit_line(d, text, max_w, size, name)
        d.text((x, baseline), text, font=f, fill=color, anchor=anchor)


def was_price(d, c: LabelContent, x: float, y: float, size: int, color=BLACK, anchor: str = "ls",
              name: str = "sans_semi") -> bool:
    if c.was_price_cents is None or c.was_price_cents <= c.price_cents:
        return False
    text = f"van {format_euro(c.was_price_cents)}"
    f = font(name, size)
    d.text((x, y), text, font=f, fill=color, anchor=anchor)
    x0, y0, x1, y1 = d.textbbox((x, y), text, font=f, anchor=anchor)
    mid = (y0 + y1) // 2 + 1
    d.line((x0 - 1, mid, x1 + 1, mid), fill=color, width=max(1, size // 9))
    return True


# --- grafische elementen -------------------------------------------------------------------------


def spaced(d, cx: float, baseline: float, text: str, f, fill, spacing: float) -> None:
    """Hoofdletters met extra letterafstand, gecentreerd."""
    widths = [d.textlength(ch, font=f) for ch in text]
    x = cx - (sum(widths) + spacing * (len(text) - 1)) / 2
    for ch, w in zip(text, widths):
        d.text((x, baseline), ch, font=f, fill=fill, anchor="ls")
        x += w + spacing


def diamond(d, cx: float, cy: float, r: float, fill) -> None:
    d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=fill)


def divider(d, x0: float, x1: float, y: float, color, r: float) -> None:
    cx = (x0 + x1) / 2
    d.line((x0, y, cx - r * 2, y), fill=color, width=1)
    d.line((cx + r * 2, y, x1, y), fill=color, width=1)
    diamond(d, cx, y, r, color)


def frame(d, box, color, width: int, gap: int, corners: bool = True) -> None:
    x0, y0, x1, y1 = box
    d.rectangle(box, outline=color, width=width)
    d.rectangle((x0 + gap, y0 + gap, x1 - gap, y1 - gap), outline=color, width=1)
    if corners:
        r = gap + 2
        for cx, cy in ((x0 + gap / 2, y0 + gap / 2), (x1 - gap / 2, y0 + gap / 2),
                       (x0 + gap / 2, y1 - gap / 2), (x1 - gap / 2, y1 - gap / 2)):
            diamond(d, cx, cy, r, color)


def starburst(d, cx: float, cy: float, r_out: float, r_in: float, points: int, fill) -> None:
    pts = []
    for i in range(points * 2):
        ang = -math.pi / 2 + i * math.pi / points
        r = r_out if i % 2 == 0 else r_in
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    d.polygon(pts, fill=fill)


def rotated_text(img: Image.Image, cx: float, cy: float, text: str, f, color, angle: float) -> None:
    x0, y0, x1, y1 = f.getbbox(text)
    layer = Image.new("L", (x1 + 4, y1 + 4), 0)
    ld = ImageDraw.Draw(layer)
    ld.fontmode = "1"
    ld.text((2, 2), text, font=f, fill=255)
    rot = layer.rotate(angle, expand=True, resample=Image.Resampling.NEAREST)
    img.paste(color, (int(cx - rot.width / 2), int(cy - rot.height / 2)), rot)


def corner_ribbon(img, d, w: int, size: int, band: int, text: str, color) -> None:
    """Schuin lint over de rechterbovenhoek."""
    d.polygon([(w - size, 0), (w - size + band, 0), (w, size - band), (w, size)], fill=color)
    cx, cy = w - size / 2 + band / 4, size / 2 - band / 4
    f = fit(d, text, band * 1.35, band * 0.62, "sans_bold")
    rotated_text(img, cx, cy, text, f, on(color), -45)


def leaf(d, cx: float, cy: float, length: float, angle_deg: float, fill, vein=WHITE) -> None:
    a = math.radians(angle_deg)
    pts = []
    for i in range(41):
        t = i / 40
        pts.append(((t - 0.5) * length, math.sin(math.pi * t) * length * 0.3))
    for i in range(40, -1, -1):
        t = i / 40
        pts.append(((t - 0.5) * length, -math.sin(math.pi * t) * length * 0.3))
    rot = [(cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)) for x, y in pts]
    d.polygon(rot, fill=fill)
    d.line((cx - length * 0.42 * math.cos(a), cy - length * 0.42 * math.sin(a),
            cx + length * 0.42 * math.cos(a), cy + length * 0.42 * math.sin(a)), fill=vein, width=max(1, int(length // 18)))


def awning(d, w: int, height: int, stripe: int, color) -> None:
    """Marktkraam-luifel: banen in kleur en wit met een geschulpte onderrand."""
    n = max(4, w // stripe)
    sw = w / n
    for i in range(n):
        x0, x1 = i * sw, (i + 1) * sw
        fill = color if i % 2 == 0 else WHITE
        d.rectangle((x0, 0, x1, height), fill=fill)
        d.pieslice((x0, height - sw / 2, x1, height + sw / 2), 0, 180, fill=fill)
        d.arc((x0, height - sw / 2, x1, height + sw / 2), 0, 180, fill=BLACK, width=1)
        d.line((x0, 0, x0, height), fill=BLACK, width=1)
    d.line((0, 0, w, 0), fill=BLACK, width=2)


def badge(d, cx: float, cy: float, r: float, text: str, fill) -> None:
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)
    d.ellipse((cx - r + 3, cy - r + 3, cx + r - 3, cy + r - 3), outline=on(fill), width=1)
    f = fit(d, text, r * 1.45, r * 0.7, "sans_bold")
    d.text((cx, cy), text, font=f, fill=on(fill), anchor="mm")


# --- ontwerpen -----------------------------------------------------------------------------------


def chalkboard(c: LabelContent, display: DisplayType) -> Image.Image:
    """Krijtbord: zwarte achtergrond, sierlijk kader, schuine schreefletter, prijs in geel of wit."""
    img, d = canvas(display, BLACK)
    w, h = display.width, display.height
    m = max(3, w // 70)
    frame(d, (m, m, w - m - 1, h - m - 1), WHITE, 1, max(3, w // 90))
    inner = m + max(3, w // 90) + max(3, w // 60)
    accent = pick(display, YELLOW, WHITE)
    y = inner + h * 0.02
    if c.promo_text:
        f, t = fit_line(d, c.promo_text.upper(), w - 2 * inner, h * 0.09, "sans_bold")
        spaced(d, w / 2, y + f.size, t, f, pick(display, YELLOW, RED, WHITE), max(1, f.size * 0.12))
        y += f.size * 1.35
    f, name = fit_line(d, c.name, w - 2 * inner, h * 0.2, "serif_bold_italic")
    d.text((w / 2, y + f.size), name, font=f, fill=WHITE, anchor="ms")
    y += f.size * 1.15
    sub = " · ".join(x for x in (c.origin, c.description) if x)
    if sub:
        fs, sub = fit_line(d, sub, w - 2 * inner, h * 0.095, "serif_italic")
        d.text((w / 2, y + fs.size), sub, font=fs, fill=WHITE, anchor="ms")
        y += fs.size * 1.2
    divider(d, w * 0.3, w * 0.7, y + h * 0.04, WHITE, max(2, h // 60))
    base = h - inner - (h * 0.06 if c.unit_price_cents is not None else 0)
    room = base - (y + h * 0.08)
    price(d, c, 0, base, w - 2 * inner, min(room * 1.25, h * 0.42), color=accent, unit_color=WHITE, center_x=w / 2)
    if was_price(d, c, inner + 2, base, max(9, int(h * 0.07)), color=WHITE, anchor="ls"):
        pass
    unit_price(d, c, w / 2, h - inner + 1, w - 2 * inner, max(8, h * 0.06), color=WHITE, anchor="ms")
    return img


def deli(c: LabelContent, display: DisplayType) -> Image.Image:
    """Delicatesse-etiket: dubbel kader met sierhoeken, schreefletter, gecentreerd, verfijnd."""
    img, d = canvas(display)
    w, h = display.width, display.height
    m = max(3, w // 60)
    gap = max(3, w // 80)
    accent = pick(display, RED, BLACK)
    frame(d, (m, m, w - m - 1, h - m - 1), BLACK, max(1, w // 150), gap)
    inner = m + gap + max(3, w // 50)
    y = inner
    if c.promo_text:
        f, t = fit_line(d, c.promo_text.upper(), w - 2 * inner, h * 0.08, "sans_bold")
        spaced(d, w / 2, y + f.size, t, f, accent, max(1, f.size * 0.18))
        y += f.size * 1.4
    f, name = fit_line(d, c.name, w - 2 * inner, h * 0.19, "serif_bold")
    d.text((w / 2, y + f.size * 0.95), name, font=f, fill=BLACK, anchor="ms")
    y += f.size * 1.1
    divider(d, w * 0.25, w * 0.75, y + 2, accent, max(2, h // 55))
    y += h * 0.05
    sub = c.description or c.origin
    if sub:
        fs, sub = fit_line(d, sub, w - 2 * inner, h * 0.09, "serif_italic")
        d.text((w / 2, y + fs.size), sub, font=fs, fill=BLACK, anchor="ms")
        y += fs.size * 1.25
    base = h - inner - (h * 0.055 if c.unit_price_cents is not None else 0)
    room = base - y
    price(d, c, 0, base, w - 2 * inner, min(room * 1.2, h * 0.38), color=accent if c.promo_text else BLACK,
          center_x=w / 2)
    was_price(d, c, inner, base, max(9, int(h * 0.065)), anchor="ls")
    unit_price(d, c, w / 2, h - m - gap - 2, w - 2 * inner, max(8, h * 0.055), anchor="ms", name="serif_italic")
    return img


def burst(c: LabelContent, display: DisplayType) -> Image.Image:
    """Knaller: prijs in een ster, naam links. Voor acties die opvallen."""
    img, d = canvas(display)
    w, h = display.width, display.height
    pad = max(4, w // 45)
    star = pick(display, RED, YELLOW)
    r_out = min(h * 0.52, w * 0.27)
    cx, cy = w - r_out - pad * 0.4, h / 2 + h * 0.02
    starburst(d, cx, cy, r_out, r_out * 0.82, 16, star)
    # ring van de andere actiekleur als die er is
    ring = pick(display, YELLOW) if star == RED and YELLOW in display.palette else None
    if ring:
        d.ellipse((cx - r_out * 0.72, cy - r_out * 0.72, cx + r_out * 0.72, cy + r_out * 0.72), outline=ring,
                  width=max(1, int(r_out // 22)))
    price(d, c, 0, cy + r_out * 0.32, r_out * 1.3, r_out * 0.75, color=on(star), center_x=cx)
    left_w = cx - r_out - pad
    head = (c.promo_text or "Actie").upper()
    f, head = fit_line(d, head, left_w, h * 0.13, "price")
    d.text((pad, pad + f.size), head, font=f, fill=star if star != YELLOW else BLACK, anchor="ls")
    y = pad + f.size * 1.25
    fn = font("sans_bold", max(9, h * 0.13))
    lines = wrap(d, c.name, left_w, fn, 2)
    for line in lines:
        d.text((pad, y + fn.size), line, font=fn, fill=BLACK, anchor="ls")
        y += fn.size * 1.1
    if c.description or c.origin:
        fs, t = fit_line(d, c.description or c.origin, left_w, h * 0.085, "sans")
        d.text((pad, y + fs.size * 1.1), t, font=fs, fill=BLACK, anchor="ls")
    was_price(d, c, pad, h - pad - (h * 0.1 if c.unit_price_cents is not None else 0), max(9, int(h * 0.09)))
    unit_price(d, c, pad, h - pad, left_w, max(8, h * 0.07))
    return img


def modern(c: LabelContent, display: DisplayType) -> Image.Image:
    """Modern: veel wit, strakke lijn, grote zware prijs; een schuin lint in de hoek bij een actie."""
    img, d = canvas(display)
    w, h = display.width, display.height
    pad = max(5, w // 30)
    accent = pick(display, RED, BLACK)
    right_room = w - 2 * pad - (h * 0.42 if c.promo_text else 0)
    fn, name = fit_line(d, c.name, right_room, h * 0.15, "sans_semi")
    d.text((pad, pad + fn.size * 0.9), name, font=fn, fill=BLACK, anchor="ls")
    y = pad + fn.size * 1.15
    sub = " · ".join(x for x in (c.origin, c.description) if x)
    if sub:
        fs, sub = fit_line(d, sub, right_room, h * 0.085, "sans")
        d.text((pad, y + fs.size), sub, font=fs, fill=BLACK, anchor="ls")
        y += fs.size * 1.3
    d.line((pad, y + h * 0.04, pad + w * 0.18, y + h * 0.04), fill=accent, width=max(2, h // 45))
    if c.promo_text:
        corner_ribbon(img, d, w, int(h * 0.55), int(h * 0.17), c.promo_text.upper(), accent)
    base = h - pad
    price(d, c, w - pad, base, w * 0.66, h * 0.5, color=accent if c.promo_text else BLACK)
    if not was_price(d, c, pad, base - (h * 0.09 if c.unit_price_cents is not None else 0), max(9, int(h * 0.08))):
        pass
    unit_price(d, c, pad, base, w * 0.32, max(8, h * 0.07))
    return img


def hangtag(c: LabelContent, display: DisplayType) -> Image.Image:
    """Prijskaartje: de prijs in een hangend kaartje met gaatje en touwtje."""
    img, d = canvas(display)
    w, h = display.width, display.height
    pad = max(4, w // 45)
    tag = pick(display, RED, BLACK) if c.promo_text else BLACK
    tw = w * 0.52
    x0, x1, y0, y1 = w - tw - pad * 0.3, w - pad * 0.5, h * 0.2, h - pad * 0.6
    tip = min((y1 - y0) * 0.42, tw * 0.3)
    ym = (y0 + y1) / 2
    d.polygon([(x0, ym), (x0 + tip, y0), (x1, y0), (x1, y1), (x0 + tip, y1)], fill=tag)
    hx, hr = x0 + tip * 0.6, max(2, min(tip * 0.16, (y1 - y0) * 0.07))
    d.ellipse((hx - hr, ym - hr, hx + hr, ym + hr), fill=WHITE)
    lw = max(1, h // 90)
    # touwtje: van het gaatje schuin omhoog naar de bovenrand, binnen de kolom van het kaartje
    d.line((hx, ym - hr, x0 + tip * 1.4, 0), fill=BLACK, width=lw)
    px0 = hx + hr * 2 + pad
    price(d, c, x1 - pad * 0.6, ym + (y1 - y0) * 0.22, x1 - px0 - pad * 0.6, (y1 - y0) * 0.62, color=WHITE)
    text_w = x0 - pad * 1.5
    y = pad
    if c.promo_text:
        f, t = fit_line(d, c.promo_text, text_w, h * 0.1, "sans_bold")
        d.text((pad, y + f.size), t, font=f, fill=pick(display, RED, BLACK), anchor="ls")
        y += f.size * 1.3
    fn, lines = fit_wrapped(d, c.name, text_w, max(9, h * 0.17), "serif_bold", 2)
    for line in lines:
        d.text((pad, y + fn.size * 0.9), line, font=fn, fill=BLACK, anchor="ls")
        y += fn.size * 1.05
    sub = c.description or c.origin
    bottom_reserved = (h * 0.1 if c.unit_price_cents is not None else 0) + (h * 0.11 if c.was_price_cents else 0)
    if sub:
        fs = font("serif_italic", max(8, h * 0.085))
        max_lines = max(1, int((h - pad - bottom_reserved - y) // (fs.size * 1.15)))
        for line in wrap(d, sub, text_w, fs, min(3, max_lines)):
            d.text((pad, y + fs.size), line, font=fs, fill=BLACK, anchor="ls")
            y += fs.size * 1.15
    was_price(d, c, pad, h - pad - (h * 0.1 if c.unit_price_cents is not None else 0), max(9, int(h * 0.085)))
    unit_price(d, c, pad, h - pad, text_w, max(8, h * 0.07))
    return img


def organic(c: LabelContent, display: DisplayType) -> Image.Image:
    """Biologisch / duurzaam: groene accenten (zwart als het display geen groen heeft), blaadjes."""
    img, d = canvas(display)
    w, h = display.width, display.height
    pad = max(4, w // 40)
    green = pick(display, GREEN, BLACK)
    band_h = h * 0.2
    d.rectangle((0, h - band_h, w, h), fill=green)
    leaf(d, pad + band_h * 0.45, h - band_h / 2, band_h * 0.75, -35, WHITE, vein=green)
    leaf(d, pad + band_h * 0.95, h - band_h / 2 + 1, band_h * 0.55, 25, WHITE, vein=green)
    label = (c.promo_text or "Biologisch").upper()
    fl, label = fit_line(d, label, w * 0.42, band_h * 0.5, "sans_bold")
    d.text((pad + band_h * 1.4, h - band_h / 2), label, font=fl, fill=WHITE, anchor="lm")
    fn, name = fit_line(d, c.name, w - 2 * pad, h * 0.16, "serif_bold")
    d.text((pad, pad + fn.size * 0.9), name, font=fn, fill=BLACK if green == BLACK else green, anchor="ls")
    y = pad + fn.size * 1.15
    sub = " · ".join(x for x in (c.origin, c.description) if x)
    if sub:
        fs, sub = fit_line(d, sub, w - 2 * pad, h * 0.085, "serif_italic")
        d.text((pad, y + fs.size), sub, font=fs, fill=BLACK, anchor="ls")
    base = h - band_h - pad * 0.6
    price(d, c, w - pad, base, w * 0.6, h * 0.36, color=BLACK)
    was_price(d, c, pad, base - (h * 0.08 if c.unit_price_cents is not None else 0), max(9, int(h * 0.07)))
    unit_price(d, c, pad, base, w * 0.36, max(8, h * 0.065))
    return img


def duo(c: LabelContent, display: DisplayType) -> Image.Image:
    """Tweekleurig: links een gekleurd vlak met de naam, rechts de prijs. Rustig en goed leesbaar."""
    img, d = canvas(display)
    w, h = display.width, display.height
    pad = max(4, w // 45)
    panel = pick(display, YELLOW, BLACK)
    pw = w * 0.46
    d.rectangle((0, 0, pw, h), fill=panel)
    txt = on(panel)
    y = pad
    if c.promo_text:
        accent = pick(display, RED, BLACK) if panel == YELLOW else WHITE
        f, t = fit_line(d, c.promo_text.upper(), pw - 2 * pad, h * 0.085, "sans_bold")
        d.text((pad, y + f.size), t, font=f, fill=accent, anchor="ls")
        y += f.size * 1.4
    room_lines = 3 if h > 150 else 2
    fn, lines = fit_wrapped(d, c.name, pw - 2 * pad, max(9, h * 0.15), "price_xb", room_lines)
    for line in lines:
        d.text((pad, y + fn.size * 0.95), line, font=fn, fill=txt, anchor="ls")
        y += fn.size * 1.05
    sub = c.origin or c.description
    if sub:
        fs, sub = fit_line(d, sub, pw - 2 * pad, h * 0.08, "sans")
        d.text((pad, h - pad), sub, font=fs, fill=txt, anchor="ls")
    rx0 = pw + pad
    base = h * 0.66
    price(d, c, 0, base, w - rx0 - pad, h * 0.42, color=pick(display, RED, BLACK) if c.promo_text else BLACK,
          center_x=(rx0 + w - pad) / 2)
    if not was_price(d, c, (rx0 + w) / 2, h * 0.2, max(9, int(h * 0.085)), anchor="ms"):
        pass
    unit_price(d, c, (rx0 + w - pad) / 2, h - pad, w - rx0 - pad, max(8, h * 0.07), anchor="ms")
    return img


def market(c: LabelContent, display: DisplayType) -> Image.Image:
    """Markt: luifel van een marktkraam bovenaan. Vrolijk voor vers, vis, groente en kaas."""
    img, d = canvas(display)
    w, h = display.width, display.height
    pad = max(4, w // 40)
    color = pick(display, RED, BLUE, BLACK)
    ah = h * 0.16
    awning(d, w, int(ah), max(14, w // 12), color)
    stripe = w / max(4, w // max(14, w // 12))
    y = ah + stripe / 2 + pad * 0.6
    if c.promo_text:
        f, t = fit_line(d, c.promo_text, w * 0.5, h * 0.09, "sans_bold")
        d.text((w - pad, y + f.size), t, font=f, fill=color, anchor="rs")
        name_w = w - 2 * pad - d.textlength(t, font=f) - pad
    else:
        name_w = w - 2 * pad
    fn, name = fit_line(d, c.name, name_w, h * 0.15, "sans_bold")
    d.text((pad, y + fn.size * 0.95), name, font=fn, fill=BLACK, anchor="ls")
    y += fn.size * 1.15
    sub = " · ".join(x for x in (c.origin, c.description) if x)
    if sub:
        fs, sub = fit_line(d, sub, w - 2 * pad, h * 0.08, "sans")
        d.text((pad, y + fs.size), sub, font=fs, fill=BLACK, anchor="ls")
    base = h - pad
    price(d, c, w - pad, base, w * 0.62, h * 0.38, color=color if c.promo_text else BLACK)
    was_price(d, c, pad, base - (h * 0.09 if c.unit_price_cents is not None else 0), max(9, int(h * 0.075)))
    unit_price(d, c, pad, base, w * 0.34, max(8, h * 0.065))
    return img
