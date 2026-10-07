# Hardware

Ontwerpdetails: [label](../docs/02-hardware-label.md) · [basisstation](../docs/03-basisstation.md) ·
[certificering](../docs/07-certificering-en-wetgeving.md).

## Voorgestelde structuur

```
hardware/
  label-2in9/        KiCad-project label 2,9" (rev A: met gecertificeerde module)
  label-4in2/
  basestation/       KiCad carrier-board voor CM5 + nRF54L15 + PoE
  enclosures/        STEP/STL behuizingen, IP65-afdichting
  production/        testjig, pogo-pin-adapter, programmeerscripts
```

Gebruik **KiCad** (gratis, tekstbestanden → goed te versiebeheren in git) en exporteer per release
Gerbers + BOM + pick-and-place naar `production/`.

## Checklist label-PCB rev A

- [ ] nRF54L15-module met geïntegreerde antenne (bespaart RF-certificering in rev A)
- [ ] FPC-connector + boostcircuit exact volgens panel-datasheet
- [ ] CR2450-houder, omgekeerde-polariteitsbescherming (P-FET, geen diode: spanningsverlies)
- [ ] NFC-antenne als PCB-spoel
- [ ] RGB-LED zichtbaar door behuizing
- [ ] Testpads: SWD, UART, VBAT, GND (raster passend op pogo-jig)
- [ ] QR-code met label-ID op silkscreen/sticker
- [ ] Meetpunt voor slaapstroom (doel: < 3 µA)

## Checklist basisstation rev A

- [ ] Start met Raspberry Pi 5 + nRF54L15-DK (USB) — nog geen eigen PCB
- [ ] Daarna: CM5-carrier, PoE 802.3af PD, nRF54L15 + optioneel nRF21540 PA/LNA
- [ ] **Ethernet**: Gigabit RJ45 met geïntegreerde magnetics, ESD-bescherming, link/activity-LED's
- [ ] **Wi-Fi**: CM5-variant mét Wi-Fi, U.FL → externe dual-band antenne (2,4 + 5 GHz) van de goedgekeurde lijst
- [ ] Antennes Wi-Fi en ESL ≥ 10–15 cm uit elkaar, orthogonaal; coexistence-meting in precompliance
- [ ] Netvoedingsingang (USB-C PD of 12 V) voor plekken zonder PoE
- [ ] Reset-knop: kort = herstart, 10 s = netwerkinstellingen terug naar fabriek (hotspot aan)
- [ ] Secure element (SE050) voor device-identiteit
- [ ] Hardware-watchdog, RTC, status-LED's
- [ ] Optioneel LTE-M modem (mini-PCIe/M.2)
