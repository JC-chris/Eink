# 2. Label-hardware

## Productlijn (voorstel)

| Type-ID | Maat | Resolutie | Kleuren | Toepassing |
|---|---|---|---|---|
| `bw_1_54` | 1,54" | 200×200 | zwart/wit | Diepvries (kleur werkt slecht < 0 °C) |
| `bwr_2_13` | 2,13" | 250×122 | zwart/wit/rood | Schap, standaard supermarkt |
| `bwry_2_9` | 2,9" | 296×128 | zwart/wit/rood/geel | Vitrine slager/vis/bakker |
| `bwry_4_2` | 4,2" | 400×300 | zwart/wit/rood/geel | Toonbank, met ingrediënten/allergenen |
| `spectra6_7_3` | 7,3" | 800×480 | 6 kleuren | Promotiebord boven de toonbank |

Deze types staan ook in de software: [`backend/eink_cloud/displays.py`](../backend/eink_cloud/displays.py).

Panelen: prototypes met **Good Display** / **Waveshare** (los verkrijgbaar, documentatie
beschikbaar); bij volume (>10k) direct bij E Ink of een panel-integrator inkopen.

## Blokschema label

```
           ┌──────────────────────────────────────────────────┐
 CR2450 ──►│ LDO/geen (nRF54L15 draait direct op 1,7–3,6 V)   │
 (620 mAh) │                                                  │
           │  nRF54L15 (SoC, 2,4 GHz, BLE 6 / ESL)            │
           │   ├─ SPI ──► FPC-connector 24p ──► e-paper panel │
           │   │          + boostcircuit (spoel, MOSFET,      │
           │   │            diodes — volgens panel-datasheet) │
           │   ├─ NFC-A antenne (koppelen met telefoon)       │
           │   ├─ RGB-LED (zoeken/pick-to-light)              │
           │   ├─ knop / reed-contact (reset, wake)           │
           │   ├─ PCB-antenne of chip-antenne 2,4 GHz         │
           │   └─ SWD + UART testpads (pogo-pins productie)   │
           └──────────────────────────────────────────────────┘
```

### Ontwerpregels PCB

- **4-laags, 0,8 mm**, impedantie-gecontroleerde RF-lijn; antenne-ontwerp volgens Nordic-referentie
  (begin met hun referentie-layout, verander zo min mogelijk).
- Eerste prototype mag een **module** gebruiken (bv. Raytac/u-blox nRF54L15-module, al gecertificeerd);
  bij volume naar losse chip voor kostprijs — dan wel zelf RF-certificeren.
- Booster-circuit van het panel exact volgens datasheet; verschillende panelen hebben verschillende
  spanningen (VGH/VGL, ±15–20 V).
- Batterij-spanningsmeting via interne ADC, met belasting (tijdens refresh) — dat geeft de echte
  restcapaciteit.
- Temperatuursensor: intern in de nRF54L15 volstaat; panel heeft zelf ook een sensor (gebruiken
  voor de juiste refresh-waveform bij kou!).
- Testpunten voor productieprogrammering + productietest (meten stroomverbruik in slaap).

## Stroombudget (indicatief, 2,9" BWRY)

| Toestand | Stroom | Duur | Per dag |
|---|---|---|---|
| Slaap + radio-sync (PAwR, 1×/2 s) | ~3–5 µA gemiddeld | 24 u | ~0,1 mAh |
| Display-refresh (kleur) | ~3–6 mA | ~15–20 s | ~0,03 mAh per update |
| 4 prijswijzigingen per dag | | | ~0,12 mAh |

Totaal ~0,25 mAh/dag → CR2450 (≈550 mAh bruikbaar) **≈ 5–6 jaar**. Grote displays (7,3"):
2× CR2450 of 2× AA, of netvoeding bij promotieborden.

## Omgeving: koel, vochtig, schoonmaakmiddelen

Dit is het onderscheidende punt voor slagers/vis/bakkers t.o.v. gewone supermarktlabels:

- **Koelvitrine 0–4 °C**: kleurenpanelen verversen traag en minder verzadigd onder ~5 °C.
  Gebruik de temperatuur-specifieke waveforms (LUT) van het panel. Testen in een klimaatkast!
- **Diepvries (−18 °C)**: kleur e-paper werkt hier praktisch niet; gebruik zwart/wit
  low-temperature panelen, of label buiten de vriezer.
- **IP65/IP67-behuizing**, condensvast (conformal coating op de PCB), afgeronde randen,
  bestand tegen chloor/alkalische reinigers (HACCP). Materiaal: PC of PC/ABS, voedselveilig
  (al is er geen direct voedselcontact). Pennen/houders voor in ijs (viswinkel) en prijsprikkers.
- Batterij vervangbaar zonder gereedschap, of (eenvoudiger + waterdicht) label gesloten en
  inruilen na 5 jaar.

## BOM-schatting (indicatief, 10k stuks, 2,9" BWRY)

| Onderdeel | € |
|---|---|
| E-paper 2,9" BWRY | 4,00 – 7,00 |
| nRF54L15 (losse chip) + kristal(len) | 1,50 – 2,20 |
| Passieven, boost, FPC-connector, LED | 0,60 – 1,00 |
| PCB + assemblage | 0,80 – 1,50 |
| CR2450 | 0,25 – 0,40 |
| Behuizing (spuitgiet, IP65) | 0,60 – 1,20 |
| **Totaal** | **≈ 8 – 13** |

Eenmalige kosten: spuitgietmatrijs €15–40k, certificering €15–30k per radiovariant.
