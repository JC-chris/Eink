import pytest

from eink_cloud.displays import DISPLAY_TYPES
from eink_cloud.render import LabelContent, format_euro, render_frame


def test_format_euro():
    assert format_euro(1295) == "€ 12,95"
    assert format_euro(5) == "€ 0,05"
    assert format_euro(123456) == "€ 1.234,56"


@pytest.mark.parametrize("display", DISPLAY_TYPES.values(), ids=lambda d: d.id)
def test_render_uses_only_palette(display):
    content = LabelContent("Zalmfilet met een hele lange naam", 2495, "kg", 2495, origin="Noorwegen", promo_text="2e halve prijs")
    frame, img = render_frame(content, display)
    assert img.size == (display.width, display.height)
    assert max(img.tobytes()) < len(display.palette)
    assert len(frame.raw) == (display.width * display.height * display.bits_per_pixel + 7) // 8


def test_render_is_deterministic():
    d = DISPLAY_TYPES["bwry_2_9"]
    c = LabelContent("Volkorenbrood", 345)
    assert render_frame(c, d)[0].crc32 == render_frame(c, d)[0].crc32
    assert render_frame(c, d)[0].crc32 != render_frame(LabelContent("Volkorenbrood", 355), d)[0].crc32
