# 3. Basisstation met zender

## Taken

1. Radioverkeer met alle labels in bereik (BLE ESL: tot ~32.000 labels per access point
   theoretisch; praktisch 1.000–3.000 per station afhankelijk van updatefrequentie).
2. Verbinding met de cloud: jobs ophalen, resultaten + telemetrie terugmelden.
3. Lokale buffer zodat de winkel blijft werken bij internetstoring.
4. Op afstand beheerbaar: OTA-updates, logs, remote support-tunnel.

## Blokschema

```
         PoE (802.3af) ──► PoE-PD + DC/DC
                                │
 ┌──────────────────────────────▼──────────────────────────────┐
 │  Linux-SoM (Raspberry Pi CM5 of NXP i.MX 8M Mini SoM)       │
 │   ├─ Ethernet (primair)                                     │
 │   ├─ Wi-Fi (optioneel, via SoM)                             │
 │   ├─ LTE-M/4G-modem (optie, fallback bij storing winkelnet) │
 │   ├─ secure element (NXP SE050 / Microchip ATECC608)        │
 │   │     → device-identiteit, mTLS-sleutel niet uitleesbaar  │
 │   ├─ eMMC (A/B-partities voor veilige OTA)                  │
 │   ├─ RTC + supercap, hardware-watchdog                      │
 │   ├─ status-LED's (power / cloud / radio)                   │
 │   └─ UART/SPI ──► nRF54L15 radio-coprocessor                │
 │                     ├─ +20 dBm PA/LNA (nRF21540) optioneel  │
 │                     └─ 2× antenne (diversity), SMA of intern│
 └─────────────────────────────────────────────────────────────┘
```

**Start pragmatisch**: prototype = Raspberry Pi 5 + nRF54L15-DK via USB. Pas na de pilot een
eigen carrier-board ontwerpen.

## Software op het basisstation

| Laag | Keuze |
|---|---|
| OS | Yocto (productie) of Raspberry Pi OS Lite (prototype) |
| OTA | **RAUC** of **Mender** met A/B-rootfs en automatische rollback |
| Agent | [`basestation/`](../basestation/) — Python nu; later eventueel Go/Rust voor kleinere footprint |
| Radio-firmware | nRF Connect SDK `central_esl` sample als basis, aangestuurd via UART (HCI of eigen commando-set) |
| Remote toegang | Uitgaande WireGuard-tunnel naar support-server, alleen aan te zetten vanuit de cloud |
| Logging | journald → periodiek gecomprimeerd naar cloud, of Loki/Vector |

## Agent (deze repository)

`eink_basestation.agent` doet in een lus:

1. **Heartbeat** (elke 30 s): versie, uptime, CPU-temperatuur + telemetrie van gehoorde labels
   (RSSI, batterij, temperatuur, getoonde CRC).
2. **Jobs ophalen** en via de radio versturen.
3. **Resultaat terugmelden** (gelukt/mislukt + CRC van het getoonde beeld).

De radio is een interface (`RadioBackend`). Er is een `SimulatedRadio` voor ontwikkeling en tests;
`NordicEslRadio` is de plek voor de echte UART-koppeling met de nRF54L15.

## Webinterface (lokaal, in het winkelnetwerk)

Elk basisstation heeft een eigen webinterface op `http://<ip-basisstation>:8080`, te gebruiken
op pc, tablet of telefoon:

| Pagina | Wat |
|---|---|
| **Status** | Cloudverbinding, labels in bereik, gelukte/mislukte updates, laatste fout |
| **Producten** | Producten en prijzen beheren (alleen in modus *webinterface*; anders alleen-lezen) |
| **Labels** | Nieuwe labels in bereik registreren, koppelen aan een product, preview, opnieuw sturen |
| **Instellingen** | **Prijsbron** (kassa ↔ webinterface), cloudserver + token, wachtwoord, apparaatinfo |

**Prijsbron omschakelen.** Een winkel zonder kassakoppeling zet de prijsbron op *Webinterface*
en beheert prijzen dan zelf. Om te voorkomen dat kassa en webinterface elkaars prijzen
overschrijven, weigert de cloud in die modus prijsupdates vanuit de kassa (HTTP 409), en
andersom. Labels koppelen kan in beide modi.

De webinterface praat via het token van het basisstation met de cloud; de cloud blijft de bron
van waarheid, zodat monitoring en support exact zien wat de winkel ziet.

**Beveiliging** (EN 18031): geen standaardwachtwoord — elk apparaat krijgt een eigen wachtwoord
(in productie op de sticker; bij eerste start zonder config wordt er een gegenereerd en gelogd).
Wachtwoord als PBKDF2-hash, sessiecookie `HttpOnly` + `SameSite=Strict`, herkomstcontrole op
formulieren, sessies vervallen na wachtwoordwijziging. Later: HTTPS met apparaatcertificaat.

**Beperking (nog te bouwen):** de webinterface heeft internet nodig, omdat de cloud de beelden
rendert. Volgende stap: rendering en een wachtrij lokaal op het basisstation, zodat prijswijzigingen
ook tijdens een internetstoring direct op de labels komen en later worden gesynchroniseerd.

## Installatie in de winkel

- Plafond- of wandmontage centraal boven de verkoopvloer; bij koelcellen/vitrines: zicht op de
  toonbank. Metalen vitrines en water/ijs dempen 2,4 GHz sterk → **sitesurvey** met testlabel
  (RSSI wordt per label gemeten en is zichtbaar in de monitoring).
- Eén PoE-kabel. Geen poorten open in de firewall nodig (alleen uitgaand 443).
