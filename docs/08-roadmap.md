# 8. Roadmap, team & kosten

## Fasering

| Fase | Duur | Resultaat |
|---|---|---|
| **0. Software-fundament** (deze repo) | gereed | Backend met kassa-API, rendering, jobs, monitoring; basisstation-agent met simulator |
| **1. Proof of concept met devkits** | 2–3 mnd | nRF54L15-DK + Waveshare/Good Display 2,9" BWRY; Nordic ESL-samples; Raspberry Pi 5 als basisstation; eerste echte label ververst vanuit de kassa-API. Bereik- en batterijmeting in een echte slagerij/koelvitrine |
| **2. Eigen label-PCB rev A** | 3–4 mnd | PCB met module, 3D-geprinte behuizing, 50 stuks; firmware: ESL + beeldformaat + telemetrie + OTA |
| **3. Basisstation rev A** | parallel, 3–4 mnd | Carrier-board voor CM5 + nRF54L15 + PoE; Yocto-image + RAUC OTA; mTLS met secure element |
| **4. Pilot** | 3 mnd | 2–3 winkels (slager, visboer, bakker), 100–300 labels per winkel, koppeling met hun kassa/weegschaal. Monitoring 24/7 |
| **5. Productierijp** | 4–6 mnd | Label rev B (losse chip, kostprijs), spuitgietmatrijs, IP65, pre-compliance + CE, productietest-jig, EMS-partner |
| **6. Lancering & schaal** | doorlopend | Meer maten (4,2", 7,3" Spectra 6), klantportaal, kassa-connectoren, PLU-importers |

Totale doorlooptijd tot verkoopbaar product: **realistisch 15–20 maanden**.

## Team (minimaal)

| Rol | FTE | Opmerking |
|---|---|---|
| Embedded/firmware (Zephyr/nRF Connect SDK, BLE) | 1–2 | Kritieke rol |
| Hardware/PCB + RF | 1 | Of extern ontwerpbureau |
| Backend/cloud + integraties | 1–2 | Bouwt verder op deze repo |
| Industrieel ontwerp/behuizing | extern | Spuitgieten, IP-rating |
| Support/installatie | 0,5 → groeit | Sitesurvey, pilot-begeleiding |

## Grove budgetindicatie tot lancering

| Post | € |
|---|---|
| Devkits, prototypes, PCB-runs (3–4 iteraties) | 20 – 40k |
| Spuitgietmatrijzen (2 maten) | 30 – 80k |
| Certificering (CE/RED, EN 18031, Bluetooth listing) | 30 – 60k |
| Testapparatuur (klimaatkast, stroommeter, spectrum-analyzer huur) | 10 – 25k |
| Cloud-hosting pilotfase | < 5k |
| Personeel (dominante post) | afhankelijk van team |

## Eerste concrete stappen (komende 4 weken)

1. Devkits bestellen: 2× nRF54L15-DK, 2,9" BWRY + 4,2" BWRY + 7,3" Spectra 6 panelen met driverboard,
   Raspberry Pi 5, Nordic PPK2 (stroommeter).
2. Nordic ESL-samples draaien en één panel aansturen met het beeldformaat uit deze repo
   (`firmware/label/src/eink_image.c`).
3. `NordicEslRadio` in de basisstation-agent implementeren → eerste end-to-end update vanuit de API.
4. Gesprek met 2–3 potentiële pilotwinkels: welke kassa/weegschaal, hoeveel labels, welke maten,
   koelvitrine-temperaturen.
5. Testlab benaderen voor een pre-compliance-gesprek.
