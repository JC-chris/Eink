# 10. Testopstelling: displays en modules om te kopen

Doel: echte e-paper displays aansturen met **dezelfde chip als op ons label (Nordic nRF54L15)**,
zodat alles wat we testen (firmware, stroomverbruik, kou, bereik) direct overgaat naar onze PCB.
De resoluties hieronder komen overeen met de displaytypes in `backend/eink_cloud/displays.py`.

> Prijzen zijn indicaties van oktober 2026. Controleer typenummer, resolutie en voorraad bij de
> leverancier, want Good Display en Waveshare hebben veel bijna-gelijke varianten.

## Aansturen: welke module

| Wat | Waarom | Indicatie |
|---|---|---|
| **2× Nordic nRF54L15-DK** | Eén als "label" (stuurt het display aan via SPI), één als radio van het basisstation (ESL central) | ± $ 40 per stuk |
| **Nordic Power Profiler Kit II (PPK2)** | Slaapstroom en stroom per refresh meten → batterijduur berekenen | ± $ 140 |
| **Raspberry Pi 5 (4 GB) + voeding + SD** | Basisstation-prototype: hier draait `basestation/` | ± € 90 |
| Jumperkabels female-female, breadboard | Display ↔ DK | ± € 10 |

Het display hangt met 8 draden aan de nRF54L15-DK (3,3 V): **VCC, GND, DIN/MOSI, CLK, CS, DC, RST, BUSY**.
Elke GPIO van de DK kan, SPI wordt in Zephyr/devicetree toegewezen.

## Displays: twee routes

### Route A: Good Display losse panelen + adapterbord (aanbevolen)

Dit zijn dezelfde panelen als we later in volume inkopen, en de adapter bevat het **boost-circuit**
dat later ook op onze label-PCB komt. Wat je hiermee leert, geldt dus één-op-één voor de PCB.

| Display | Typenummer | Resolutie | Kleuren | Adapter |
|---|---|---|---|---|
| 2,9" vitrinelabel | GDEY029F52 | 296×128 | zwart/wit/rood/geel, refresh ± 11 s | DESPI-C02 (24-pin) |
| 2,9" hoge resolutie | GDEY029F51H | 384×168 | zwart/wit/rood/geel | DESPI-C02 |
| 7,3" promotiebord | GDEP073E01 | 800×480 | Spectra 6 (6 kleuren) | DESPI-C73 (50-pin) |
| 4,2" / 2,13" / 1,54" | vraag de 4-kleuren- en zwart-witvarianten aan bij Good Display | 400×300 / 250×122 / 200×200 | | meestal DESPI-C02 |

Koop **2 à 3 stuks per type** (eentje gaat bij het experimenteren altijd stuk; FPC-kabels zijn kwetsbaar),
en 2–3 DESPI-C02 adapters.

### Route B: Waveshare modules met driverbord (snelste start)

Kant-en-klaar met driverbord, kabel en voorbeeldcode. Ideaal voor een eerste demo binnen een dag;
minder representatief voor onze eigen PCB.

| Display | Product | Resolutie | Kleuren |
|---|---|---|---|
| 2,13" | 2.13inch e-Paper HAT (G) | 250×122 | rood/geel/zwart/wit |
| 2,9" | 2.9inch e-Paper Module (G) | 296×128 | rood/geel/zwart/wit (± 16 s) |
| 4,2" | 4.2inch e-Paper Module (G) | 400×300 | rood/geel/zwart/wit (± 21 s) |
| 7,3" | 7.3inch e-Paper HAT (E) | 800×480 | Spectra 6 |
| 1,54" | 1.54inch e-Paper Module (zwart/wit) | 200×200 | zwart/wit (diepvries-test) |

## Aanbevolen eerste bestelling

1. 2× nRF54L15-DK, 1× PPK2, 1× Raspberry Pi 5 set.
2. Route A: 3× GDEY029F52 + 3× DESPI-C02, 1× GDEP073E01 + 1× DESPI-C73.
3. Route B voor de snelle demo: 1× Waveshare 2.9" (G) module en 1× 4.2" (G) module.

## Wat we ermee testen

| Test | Hoe | Waarom |
|---|---|---|
| Beeld tonen | Frame uit de cloud (`/preview.png` / job) decoderen met `firmware/label/src/eink_image.c` | Hele keten bewijzen |
| Kleuren en ontwerpen | Alle 15 ontwerpen op het echte panel | Hoe ziet het er echt uit, niet op een scherm |
| Refresh in de kou | Panel in een koelkast (2–4 °C) en vriezer (−18 °C) | Kleurpanelen worden traag en flets in de kou |
| Stroom | PPK2: slaapstroom, energie per refresh | Batterijduur van 5+ jaar onderbouwen |
| Bereik | DK in een koelvitrine / tussen ijs bij een visboer | 2,4 GHz-demping door water en metaal |
