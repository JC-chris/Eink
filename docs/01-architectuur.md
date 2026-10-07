# 1. Architectuur & belangrijkste keuzes

## Het systeem in vier lagen

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 4. Integraties   Kassa (REST), weegschaal-PLU-bestanden (CSV/SFTP),      │
│                  webshop, ERP                                            │
├──────────────────────────────────────────────────────────────────────────┤
│ 3. Cloud         API · productdatabase · template-rendering ·            │
│                  job-queue + retries · monitoring/alerts · OTA-beheer    │
├──────────────────────────────────────────────────────────────────────────┤
│ 2. Basisstation  Linux-SoM + nRF54L15 radio-coprocessor · lokale cache   │
│   (per winkel)   · PoE · Ethernet/Wi-Fi/LTE · werkt door bij storing     │
├──────────────────────────────────────────────────────────────────────────┤
│ 1. Labels        nRF54L15 + e-paper (2–6 kleuren) · CR2450 · NFC ·       │
│                  LED · 5+ jaar batterijduur                              │
└──────────────────────────────────────────────────────────────────────────┘
```

## Kernbeslissingen (aanbeveling)

| Onderwerp | Keuze | Waarom |
|---|---|---|
| Radio | **2,4 GHz, Bluetooth LE "ESL"-profiel (PAwR)** op Nordic nRF54L15 | Open standaard (Bluetooth SIG, 2023), extreem zuinig, Nordic levert referentie-code (`central_esl` / `peripheral_esl` in nRF Connect SDK). Scheelt 6–12 maanden eigen protocolontwikkeling. Eigen protocol blijft mogelijk op dezelfde chip. |
| Alternatief radio | Sub-GHz 868 MHz (TI CC1312/CC1352) | Beter bereik door koelcellen, water en ijs (viswinkel). Lagere datasnelheid → trage updates van grote displays. Pas overwegen als bereiktests op 2,4 GHz tegenvallen. |
| Display | E Ink **Spectra 3100** (zwart/wit/rood/geel) voor kleine labels, **Spectra 6** (6 kleuren) voor 7,3"–13,3" | Rood/geel = aanbiedingen, prijsacties. Spectra 6 voor promotieborden boven de toonbank. |
| Rendering | **In de cloud** naar bitmap, label toont alleen pixels | Labels blijven dom en goedkoop; layouts aanpassen zonder firmware-update; preview = exact wat het label toont. |
| Basisstation ↔ cloud | Uitgaand HTTPS (poll), later MQTT/WebSocket | Werkt door elke winkelfirewall heen, geen poorten openzetten. |
| Kassakoppeling | REST-API + CSV/SFTP-import | Moderne kassa's via API; weegschalen (Bizerba, Mettler Toledo, Dibal, Digi) exporteren PLU-bestanden. |
| Backend | Python/FastAPI + PostgreSQL (SQLite in ontwikkeling) | Snel te bouwen, goed te testen; schaalbaar genoeg tot honderden winkels. |

## Datastroom bij een prijswijziging

1. Kassa stuurt `PUT /v1/stores/{winkel}/products/{sku}` met nieuwe prijs.
2. Cloud zoekt alle labels die aan die SKU gekoppeld zijn en rendert per label een bitmap
   in het kleurenpalet van dat display (incl. verplichte **eenheidsprijs per kg**).
3. Bitmap wordt gecomprimeerd (RLE) met een CRC32 en als **update-job** klaargezet.
   Oudere, nog niet verzonden jobs voor hetzelfde label vervallen (`superseded`).
4. Basisstation haalt jobs op, verstuurt ze via de radio, het label decodeert,
   ververst het scherm en meldt de CRC van wat het **werkelijk toont** terug.
5. Cloud vergelijkt getoonde CRC met verwachte CRC. Mislukt? Automatisch opnieuw
   (max. 3×), daarna **alert** naar support.

## Werken bij storingen

- **Internet weg**: basisstation houdt jobs in een lokale wachtrij en blijft labels bedienen
  (fase 2: lokale kassa-API op het basisstation zodat prijswijzigingen ook offline doorkomen).
- **Basisstation weg**: labels blijven gewoon het laatste beeld tonen (e-paper heeft geen stroom
  nodig om beeld vast te houden). Alert naar support na 5 minuten.
- **Label buiten bereik**: label meldt zich bij elk basisstation in de winkel; jobs gaan via het
  basisstation dat het label het laatst gehoord heeft.

## Multi-tenant

Elke winkel (`store`) heeft een eigen API-sleutel voor de kassa en eigen basisstations.
Ketens kunnen later een `organisation`-niveau krijgen boven winkels.
