"""Labelontwerpen (sjablonen).

Elk ontwerp tekent een product op het display in de kleuren die dat display heeft. Er wordt altijd
teruggevallen op zwart als een kleur ontbreekt, zodat elk ontwerp op elk display werkt.
Wettelijk verplicht en daarom in elk ontwerp: verkoopprijs en, indien opgegeven, de eenheidsprijs.

Een ontwerp toevoegen: schrijf een functie (content, display) → Image en zet hem in TEMPLATES.
Houd het deterministisch (geen datum/tijd, geen willekeur): de CRC-controle vergelijkt het
verwachte beeld met wat het label toont.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image, ImageDraw

from .displays import BLACK, BLUE, RED, WHITE, YELLOW, DisplayType
from .render import LabelContent, _fit, _font, format_euro, render_standard


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    description: str
    suited_for: str
    render: Callable[[LabelContent, DisplayType], Image.Image]


# --- bouwstenen ----------------------------------------------------------------------------------


def _canvas(display: DisplayType) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (display.width, display.height), WHITE)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"  # scherpe tekst op e-paper
    return img, d


def _color(display: DisplayType, *preferred) -> tuple[int, int, int]:
    return next((c for c in preferred if c in display.palette), BLACK)


def _on(color: tuple[int, int, int]) -> tuple[int, int, int]:
    """Leesbare tekstkleur op een gekleurde achtergrond."""
    return BLACK if color in (YELLOW, WHITE) else WHITE


def _pad(display: DisplayType) -> int:
    return max(4, display.width // 50)


def _price(d: ImageDraw.ImageDraw, content: LabelContent, right: int, bottom: int, max_w: int, size: int,
           color=BLACK, anchor_center: bool = False, center_x: int | None = None) -> int:
    """Prijs met '/kg' erachter. Geeft de hoogte van het prijsblok terug."""
    price = format_euro(content.price_cents)
    suffix = f"/{content.unit}" if content.unit != "st" else ""
    f_suffix = _font(max(8, size // 3))
    suffix_w = d.textlength(suffix, font=f_suffix) if suffix else 0
    f_price = _fit(d, price, max_w - int(suffix_w), size, bold=True)
    if anchor_center:
        total = d.textlength(price, font=f_price) + suffix_w
        right = int(center_x + total / 2)
    d.text((right - suffix_w, bottom), price, font=f_price, fill=color, anchor="rd")
    if suffix:
        d.text((right, bottom), suffix, font=f_suffix, fill=BLACK, anchor="rd")
    return f_price.size


def _unit_price(d: ImageDraw.ImageDraw, content: LabelContent, x: int, bottom: int, max_w: int, size: int,
                anchor: str = "ld") -> None:
    if content.unit_price_cents is not None:
        text = f"{format_euro(content.unit_price_cents)} per {content.unit_price_unit}"
        d.text((x, bottom), text, font=_fit(d, text, max_w, size), fill=BLACK, anchor=anchor)


def _wrap(d: ImageDraw.ImageDraw, text: str, size: int, max_w: int, max_lines: int, bold: bool = False) -> list[str]:
    """Tekst over meerdere regels; afgekapt met … als hij niet past."""
    font = _font(size, bold)
    words, lines, line = text.split(), [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if d.textlength(candidate, font=font) <= max_w:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = word
        if len(lines) == max_lines:
            break
    if line and len(lines) < max_lines:
        lines.append(line)
    if len(lines) == max_lines and " ".join(lines) != " ".join(words):
        last = lines[-1]
        while last and d.textlength(last + "…", font=font) > max_w:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _line(d: ImageDraw.ImageDraw, text: str, max_w: int, size: int, bold: bool = False):
    """Lettergrootte die past; past het zelfs op de kleinste grootte niet, dan afkappen met …"""
    font = _fit(d, text, max_w, size, bold)
    if d.textlength(text, font=font) <= max_w:
        return font, text
    while text and d.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return font, text.rstrip() + "…"


def _strike(d: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int, color=BLACK, anchor: str = "la") -> None:
    font = _font(size)
    d.text(xy, text, font=font, fill=color, anchor=anchor)
    x0, y0, x1, y1 = d.textbbox(xy, text, font=font, anchor=anchor)
    mid = (y0 + y1) // 2
    d.line((x0 - 1, mid, x1 + 1, mid), fill=color, width=max(1, size // 10))


# --- ontwerpen -----------------------------------------------------------------------------------


def render_action(c: LabelContent, display: DisplayType) -> Image.Image:
    """Aanbieding: rode balk, doorgestreepte van-prijs, grote rode prijs."""
    img, d = _canvas(display)
    w, h, pad = display.width, display.height, _pad(display)
    band = _color(display, RED, YELLOW)
    band_h = int(h * 0.22)
    d.rectangle((0, 0, w, band_h), fill=band)
    title = (c.promo_text or "Aanbieding").upper()
    d.text((w / 2, band_h / 2), title, font=_fit(d, title, w - 2 * pad, int(band_h * 0.7), bold=True),
           fill=_on(band), anchor="mm")
    y = band_h + pad // 2
    f_name = _fit(d, c.name, w - 2 * pad, int(h * 0.14), bold=True)
    d.text((pad, y), c.name, font=f_name, fill=BLACK)
    y += f_name.size + pad // 2
    if c.was_price_cents is not None and c.was_price_cents > c.price_cents:
        _strike(d, (pad, y), f"van {format_euro(c.was_price_cents)}", int(h * 0.11))
    _price(d, c, w - pad, h - pad, int(w * 0.66), int(h * 0.38), color=_color(display, RED))
    _unit_price(d, c, pad, h - pad, int(w * 0.32), int(h * 0.08))
    return img


def render_craft(c: LabelContent, display: DisplayType) -> Image.Image:
    """Ambachtelijk (slager): zwarte kopbalk met witte naam, herkomst eronder, klassiek toonbankbord."""
    img, d = _canvas(display)
    w, h, pad = display.width, display.height, _pad(display)
    head_h = int(h * 0.30)
    d.rectangle((0, 0, w, head_h), fill=BLACK)
    d.text((w / 2, head_h / 2), c.name, font=_fit(d, c.name, w - 2 * pad, int(head_h * 0.62), bold=True),
           fill=WHITE, anchor="mm")
    y = head_h + pad // 2
    sub = " · ".join(x for x in (c.origin, c.description) if x)
    if sub:
        font, sub = _line(d, sub, w - 2 * pad, int(h * 0.10))
        d.text((w / 2, y), sub, font=font, fill=BLACK, anchor="ma")
    if c.promo_text:
        accent = _color(display, RED)
        f = _fit(d, c.promo_text, int(w * 0.34), int(h * 0.10), bold=True)
        d.text((pad, h - pad - int(h * 0.12)), c.promo_text, font=f, fill=accent, anchor="ld")
    rule_y = int(h * 0.50)
    d.line((pad, rule_y, w - pad, rule_y), fill=BLACK, width=max(1, h // 100))
    _price(d, c, w - pad, h - pad, int(w * 0.62), int(h * 0.38),
           color=_color(display, RED) if c.promo_text else BLACK)
    _unit_price(d, c, pad, h - pad, int(w * 0.34), int(h * 0.08))
    return img


def render_fish(c: LabelContent, display: DisplayType) -> Image.Image:
    """Vis: naam, Latijnse naam/vangstmethode (omschrijving) en vangstgebied (herkomst).

    EU-verordening 1379/2013 verplicht bij verse vis: handelsbenaming, wetenschappelijke naam,
    productiemethode (gevangen/gekweekt), vangstgebied en vistuig. Zet de wetenschappelijke naam en
    methode in de omschrijving en het vangstgebied in de herkomst.
    """
    img, d = _canvas(display)
    w, h, pad = display.width, display.height, _pad(display)
    accent = _color(display, BLUE, BLACK)
    d.rectangle((0, 0, max(4, w // 60), h), fill=accent)  # zijbalk
    x = max(4, w // 60) + pad
    y = pad
    f_name = _fit(d, c.name, w - x - pad, int(h * 0.17), bold=True)
    d.text((x, y), c.name, font=f_name, fill=accent if accent != BLACK else BLACK)
    y += f_name.size + pad // 2
    small = int(h * 0.085)
    for line in (c.description, f"Vangstgebied: {c.origin}" if c.origin else None):
        if line:
            font, line = _line(d, line, w - x - pad, small)
            d.text((x, y), line, font=font, fill=BLACK)
            y += font.size + 2
    if c.promo_text:
        f = _fit(d, c.promo_text, int(w * 0.34), small, bold=True)
        d.text((x, h - pad - small - 4), c.promo_text, font=f, fill=_color(display, RED), anchor="ld")
    _price(d, c, w - pad, h - pad, int(w * 0.58), int(h * 0.34))
    _unit_price(d, c, x, h - pad, int(w * 0.36), small)
    return img


def render_bakery(c: LabelContent, display: DisplayType) -> Image.Image:
    """Bakker: gecentreerd, grote prijs, warme balk onderaan ('Vers gebakken' of de actietekst)."""
    img, d = _canvas(display)
    w, h, pad = display.width, display.height, _pad(display)
    band = _color(display, YELLOW, RED)
    band_h = int(h * 0.20)
    d.rectangle((0, h - band_h, w, h), fill=band)
    text = c.promo_text or "Vers gebakken"
    d.text((w / 2, h - band_h / 2), text, font=_fit(d, text, w - 2 * pad, int(band_h * 0.65), bold=True),
           fill=_on(band), anchor="mm")
    f_name = _fit(d, c.name, w - 2 * pad, int(h * 0.15), bold=True)
    d.text((w / 2, pad), c.name, font=f_name, fill=BLACK, anchor="ma")
    y = pad + f_name.size + 2
    if c.description:
        font, text = _line(d, c.description, w - 2 * pad, int(h * 0.085))
        d.text((w / 2, y), text, font=font, fill=BLACK, anchor="ma")
    _price(d, c, 0, h - band_h - pad // 2, w - 2 * pad, int(h * 0.36), anchor_center=True, center_x=w // 2)
    if c.unit_price_cents is not None:
        _unit_price(d, c, w - pad, h - band_h - pad // 2, int(w * 0.25), int(h * 0.07), anchor="rd")
    return img


def render_minimal(c: LabelContent, display: DisplayType) -> Image.Image:
    """Minimaal: naam klein bovenaan, prijs zo groot mogelijk. Goed leesbaar op afstand en op kleine labels."""
    img, d = _canvas(display)
    w, h, pad = display.width, display.height, _pad(display)
    f_name = _fit(d, c.name, w - 2 * pad, int(h * 0.16), bold=True)
    d.text((w / 2, pad), c.name, font=f_name, fill=BLACK, anchor="ma")
    color = _color(display, RED) if c.promo_text else BLACK
    bottom = h - pad - (int(h * 0.10) if c.unit_price_cents is not None else 0)
    _price(d, c, 0, bottom, w - 2 * pad, int(h * 0.55), color=color, anchor_center=True, center_x=w // 2)
    if c.unit_price_cents is not None:
        _unit_price(d, c, w // 2, h - pad, w - 2 * pad, int(h * 0.08), anchor="md")
    return img


def render_info(c: LabelContent, display: DisplayType) -> Image.Image:
    """Info: voor grotere displays. Naam, omschrijving over meerdere regels (ingrediënten, allergenen,
    bereidingstip), herkomst en een prijsvlak rechtsonder."""
    img, d = _canvas(display)
    w, h, pad = display.width, display.height, _pad(display)
    y = pad
    if c.promo_text:
        band = _color(display, YELLOW, RED)
        band_h = int(h * 0.12)
        d.rectangle((0, 0, w, band_h), fill=band)
        d.text((w / 2, band_h / 2), c.promo_text, font=_fit(d, c.promo_text, w - 2 * pad, int(band_h * 0.7), bold=True),
               fill=_on(band), anchor="mm")
        y = band_h + pad // 2
    f_name = _fit(d, c.name, w - 2 * pad, int(h * 0.12), bold=True)
    d.text((pad, y), c.name, font=f_name, fill=BLACK)
    y += f_name.size + pad
    box_h = int(h * 0.34)
    text_size = max(9, int(h * 0.06))
    if c.description:
        max_lines = max(1, (h - box_h - y - pad) // (text_size + 3) - (1 if c.origin else 0))
        for line in _wrap(d, c.description, text_size, w - 2 * pad, max_lines):
            d.text((pad, y), line, font=_font(text_size), fill=BLACK)
            y += text_size + 3
    if c.origin:
        font, line = _line(d, f"Herkomst: {c.origin}", w - 2 * pad, text_size, bold=True)
        d.text((pad, y + 2), line, font=font, fill=BLACK)
    # prijsvlak
    box_w = int(w * 0.55)
    x0, y0 = w - box_w, h - box_h
    fill = _color(display, RED) if c.promo_text else BLACK
    d.rectangle((x0, y0, w, h), fill=fill)
    price = format_euro(c.price_cents)
    suffix = f"/{c.unit}" if c.unit != "st" else ""
    f_suffix = _font(max(8, box_h // 4))
    sw = d.textlength(suffix, font=f_suffix) if suffix else 0
    was = c.was_price_cents is not None and c.was_price_cents > c.price_cents
    was_size = max(9, box_h // 5)
    # Met van-prijs: die bovenin het vlak, de prijs eronder kleiner zodat ze elkaar niet raken.
    price_room = box_h - 2 * pad - (was_size + 2 if was else 0)
    f_price = _fit(d, price, box_w - 2 * pad - int(sw), int(price_room * 0.95), bold=True)
    d.text((w - pad - sw, h - pad), price, font=f_price, fill=WHITE, anchor="rd")
    if suffix:
        d.text((w - pad, h - pad), suffix, font=f_suffix, fill=WHITE, anchor="rd")
    if was:
        _strike(d, (x0 + pad, y0 + pad // 2), f"van {format_euro(c.was_price_cents)}", was_size, color=WHITE)
    _unit_price(d, c, pad, h - pad, x0 - 2 * pad, text_size)
    return img


TEMPLATES: dict[str, Template] = {t.id: t for t in (
    Template("standaard", "Standaard", "Naam, herkomst en grote prijs; actiebalk als er een actietekst is.",
             "Alle winkels", render_standard),
    Template("actie", "Actie", "Rode balk, doorgestreepte van-prijs en grote rode prijs.",
             "Aanbiedingen, weekacties", render_action),
    Template("ambachtelijk", "Ambachtelijk", "Zwarte kopbalk met de naam, herkomst eronder; klassiek toonbankbord.",
             "Slagerij, kaas, delicatessen", render_craft),
    Template("vis", "Vis", "Vangstgebied en Latijnse naam/vangstmethode (EU-etikettering verse vis).",
             "Viswinkel, visafdeling", render_fish),
    Template("bakker", "Bakker", "Gecentreerd met een warme balk 'Vers gebakken' of de actietekst.",
             "Bakkerij, banket", render_bakery),
    Template("minimaal", "Minimaal", "Alleen naam en een zo groot mogelijke prijs.",
             "Kleine labels, op afstand leesbaar", render_minimal),
    Template("info", "Info", "Omschrijving over meerdere regels (ingrediënten, allergenen), prijsvlak.",
             "Grote displays (4,2 inch en groter)", render_info),
)}
