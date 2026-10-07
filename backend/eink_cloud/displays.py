"""Catalogus van ondersteunde e-paper displays en hun kleurpaletten.

De volgorde van de kleuren in een palet is de pixelwaarde die naar het label gaat
(zie firmware/label/src/eink_image.h). Die volgorde mag dus nooit veranderen.
"""

from dataclasses import dataclass

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (200, 0, 0)
YELLOW = (240, 200, 0)
BLUE = (0, 60, 160)
GREEN = (0, 130, 60)

# palette_id -> kleuren (index = pixelwaarde)
PALETTES: dict[int, tuple[tuple[int, int, int], ...]] = {
    0: (BLACK, WHITE),
    1: (BLACK, WHITE, RED),
    2: (BLACK, WHITE, RED, YELLOW),
    3: (BLACK, WHITE, RED, YELLOW, BLUE, GREEN),
}


@dataclass(frozen=True)
class DisplayType:
    id: str
    description: str
    width: int
    height: int
    palette_id: int

    @property
    def palette(self) -> tuple[tuple[int, int, int], ...]:
        return PALETTES[self.palette_id]

    @property
    def bits_per_pixel(self) -> int:
        n = len(self.palette)
        return 1 if n <= 2 else 2 if n <= 4 else 4


DISPLAY_TYPES: dict[str, DisplayType] = {
    d.id: d
    for d in (
        DisplayType("bw_1_54", '1,54" zwart/wit (diepvries)', 200, 200, 0),
        DisplayType("bwr_2_13", '2,13" zwart/wit/rood', 250, 122, 1),
        DisplayType("bwry_2_9", '2,9" zwart/wit/rood/geel', 296, 128, 2),
        DisplayType("bwry_4_2", '4,2" zwart/wit/rood/geel', 400, 300, 2),
        DisplayType("spectra6_7_3", '7,3" Spectra 6 (6 kleuren)', 800, 480, 3),
    )
}
