"""Rendert een product naar een label-bitmap in het palet van het display."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .displays import BLACK, RED, WHITE, YELLOW, DisplayType
from .imageformat import Frame, build_frame


@dataclass
class LabelContent:
    name: str
    price_cents: int
    unit: str = "st"
    unit_price_cents: int | None = None
    unit_price_unit: str = "kg"
    origin: str | None = None
    promo_text: str | None = None


def format_euro(cents: int) -> str:
    euros, rest = divmod(cents, 100)
    return f"€ {euros:,}".replace(",", ".") + f",{rest:02d}"


# Fonts zitten in de repo: rendering moet op elke server bit-voor-bit gelijk zijn,
# anders klopt de CRC-vergelijking tussen verwacht en getoond beeld niet.
FONT_DIR = Path(__file__).parent / "fonts"


@lru_cache(maxsize=256)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), max(size, 8))


def _fit(draw: ImageDraw.ImageDraw, text: str, max_w: int, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    while size > 8:
        f = _font(size, bold)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 1
    return _font(8, bold)


def render_image(content: LabelContent, display: DisplayType) -> Image.Image:
    w, h = display.width, display.height
    img = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"  # geen anti-aliasing: anders gekleurde randpixels op e-paper
    pad = max(4, w // 50)
    palette = display.palette
    accent = RED if RED in palette else BLACK
    y = pad

    if content.promo_text:
        band_h = int(h * 0.18)
        band_color = YELLOW if YELLOW in palette else accent
        text_color = BLACK if band_color == YELLOW else WHITE
        d.rectangle((0, 0, w, band_h), fill=band_color)
        f = _fit(d, content.promo_text, w - 2 * pad, int(band_h * 0.75), bold=True)
        d.text((w / 2, band_h / 2), content.promo_text, font=f, fill=text_color, anchor="mm")
        y = band_h + pad // 2

    f_name = _fit(d, content.name, w - 2 * pad, int(h * 0.15), bold=True)
    d.text((pad, y), content.name, font=f_name, fill=BLACK)
    y += f_name.size + pad // 2

    if content.origin:
        f_small = _fit(d, content.origin, w - 2 * pad, int(h * 0.09))
        d.text((pad, y), content.origin, font=f_small, fill=BLACK)

    # Prijs groot rechtsonder; per kg-producten krijgen "/kg" erachter.
    price = format_euro(content.price_cents)
    suffix = f"/{content.unit}" if content.unit != "st" else ""
    f_suffix = _font(int(h * 0.12))
    suffix_w = d.textlength(suffix, font=f_suffix) if suffix else 0
    f_price = _fit(d, price, int(w * 0.62) - suffix_w, int(h * 0.36), bold=True)
    price_color = accent if content.promo_text else BLACK
    right = w - pad - suffix_w
    d.text((right, h - pad), price, font=f_price, fill=price_color, anchor="rd")
    if suffix:
        d.text((w - pad, h - pad), suffix, font=f_suffix, fill=BLACK, anchor="rd")

    # Eenheidsprijs (Besluit prijsaanduiding producten) linksonder.
    if content.unit_price_cents is not None:
        text = f"{format_euro(content.unit_price_cents)} per {content.unit_price_unit}"
        f_unit = _fit(d, text, int(w * 0.36), int(h * 0.09))
        d.text((pad, h - pad), text, font=f_unit, fill=BLACK, anchor="ld")

    return img


def render_notice_image(display: DisplayType, title: str, subtitle: str = "") -> Image.Image:
    """Neutraal beeld zonder prijs, bv. als de dienst is uitgeschakeld."""
    w, h = display.width, display.height
    img = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    pad = max(4, w // 25)
    f_title = _fit(d, title, w - 2 * pad, int(h * 0.22), bold=True)
    d.text((w / 2, h * 0.42), title, font=f_title, fill=BLACK, anchor="mm")
    if subtitle:
        f_sub = _fit(d, subtitle, w - 2 * pad, int(h * 0.11))
        d.text((w / 2, h * 0.70), subtitle, font=f_sub, fill=BLACK, anchor="mm")
    return img


def notice_frame(display: DisplayType, title: str, subtitle: str = "") -> Frame:
    q = quantize(render_notice_image(display, title, subtitle), display)
    return build_frame(q.tobytes(), display.width, display.height, display.bits_per_pixel, display.palette_id)


def quantize(img: Image.Image, display: DisplayType) -> Image.Image:
    """Zet om naar exact het palet van het display (geen dithering: tekst blijft scherp)."""
    pal_img = Image.new("P", (1, 1))
    flat = [c for rgb in display.palette for c in rgb]
    pal_img.putpalette(flat + flat[:3] * (256 - len(display.palette)))
    q = img.convert("RGB").quantize(palette=pal_img, dither=Image.Dither.NONE)
    n = len(display.palette)
    # Opvulling van het palet is zwart: indexen >= n zijn dus index 0.
    return q.point(lambda v: v if v < n else 0)


def render_frame(content: LabelContent, display: DisplayType) -> tuple[Frame, Image.Image]:
    q = quantize(render_image(content, display), display)
    frame = build_frame(q.tobytes(), display.width, display.height, display.bits_per_pixel, display.palette_id)
    return frame, q


def frame_to_png_image(frame: Frame, display: DisplayType) -> Image.Image:
    """Reconstrueert het beeld uit het frame — exact wat het label toont."""
    from .imageformat import unpack_pixels

    idx = unpack_pixels(frame.raw, frame.bits_per_pixel, frame.width * frame.height)
    img = Image.frombytes("P", (frame.width, frame.height), idx)
    flat = [c for rgb in display.palette for c in rgb]
    img.putpalette(flat)
    return img.convert("RGB")
