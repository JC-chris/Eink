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
 │   ├─ Ethernet 10/100/1000 (RJ45, + PoE)          — verplicht │
 │   ├─ Wi-Fi 2,4 + 5 GHz (802.11ac, ext. antenne)  — verplicht │
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

## Netwerkaansluiting: Ethernet én Wi-Fi

Beide aansluitingen zijn standaard aanwezig, want niet elke winkel heeft een kabel op de plek waar
het basisstation moet hangen.

| | Ethernet | Wi-Fi |
|---|---|---|
| Hardware | Gigabit-PHY (in SoM), RJ45 met magnetics, PoE 802.3af | Gecertificeerde Wi-Fi 5-module (CM5 heeft deze ingebouwd), 2,4 + 5 GHz, U.FL naar externe antenne |
| Gebruik | Voorkeur: stabiel en voeding via dezelfde kabel | Als er geen kabel is, of als reserve wanneer Ethernet uitvalt |
| Voorrang | route-metric 100 | route-metric 600: Ethernet wint als beide verbonden zijn |
| Instellen | DHCP (standaard) of vast IP | Netwerken zoeken, verbinden (WPA2/WPA3-Personal), verborgen SSID, vergeten |

**Wi-Fi en de labelradio zitten allebei op 2,4 GHz.** Dat is het grootste ontwerprisico van het
basisstation. Maatregelen:

1. **Bij voorkeur Wi-Fi op 5 GHz.** De webinterface toont de netwerken; adviseer de installateur
   het 5 GHz-netwerk te kiezen. Dan is er geen storing met de labels.
2. **Antennes scheiden.** Wi-Fi- en ESL-antenne minimaal 10–15 cm uit elkaar en haaks op elkaar
   (orthogonale polarisatie). Liefst ook aan verschillende zijden van de behuizing.
3. **Kanaalplanning.** BLE ESL (PAwR) gebruikt de advertising-kanalen 37/38/39 en hopt over de
   datakanalen. De radio kan via *channel map* de Wi-Fi-kanalen die in gebruik zijn vermijden;
   de agent kan het actieve Wi-Fi-kanaal doorgeven aan de nRF54L15.
4. **Meten in de EMC-/RF-precompliance:** gevoeligheid van de ESL-radio met Wi-Fi actief op vol vermogen.

Netwerkbeheer op het apparaat gebeurt met **NetworkManager** (`nmcli`). De agent maakt eigen,
herkenbare verbindingen aan (`eink-ethernet`, `eink-wifi`, `eink-hotspot`) en raakt de rest niet aan.

### Installatie-hotspot

Een basisstation zonder werkende netwerkinstelling moet je altijd kunnen bereiken:

1. Heeft het basisstation **2 minuten** geen Ethernet en geen Wi-Fi, dan start het een eigen
   Wi-Fi-netwerk **`Eink-XXXX`**. Netwerknaam en wachtwoord zijn uniek per apparaat en staan op de sticker.
2. De installateur verbindt met telefoon of laptop en opent **`http://10.42.0.1:8080`**.
3. Bij *Netwerk* kiest de installateur het winkel-Wi-Fi (of steekt een kabel in). De hotspot gaat
   uit en het basisstation zit in het winkelnetwerk.
4. Verkeerd wachtwoord of foute instelling? Dan is er na 2 minuten weer geen netwerk en komt de
   hotspot vanzelf terug. Een verkeerde instelling kan het apparaat dus niet onbereikbaar maken.
5. Gaat de Ethernet-kabel erin, dan stopt een actieve hotspot direct.

De hotspot is in de webinterface uit te zetten. Dat raden we niet aan.

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
| **Producten** | Producten en prijzen beheren: met de hand (met naamsuggesties), uit het **standaard assortiment** van de branche, of met een **Excel/CSV-prijslijst** (alleen in modus *webinterface*; anders alleen-lezen) |
| **Labels** | Nieuwe labels in bereik registreren, koppelen aan een product, preview, opnieuw sturen |
| **Ontwerp** | Standaard labelontwerp van de winkel kiezen, met voorbeelden per displaytype (met en zonder actie) |
| **Netwerk** | Status Ethernet/Wi-Fi (IP, gateway, DNS, signaal), Ethernet DHCP of vast IP, Wi-Fi zoeken/verbinden/vergeten, installatie-hotspot |
| **Instellingen** | **Prijsbron** (kassa/weegschaal ↔ webinterface), **importmap**, cloudserver + token, wachtwoord, apparaatinfo |

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

## Importmap voor exports van weegschaal of kassa

Veel slagers en bakkers hebben een weegschaal-kassa (Bizerba, Mettler Toledo, Digi, Dibal). De
prijzen staan dan in de weegschaalsoftware, en die kan een artikellijst exporteren. Het
basisstation pakt die export op:

1. Zet in de webinterface bij *Instellingen* de **importmap** aan (standaard
   `/var/lib/eink-basestation/import`).
2. Maak die map bereikbaar voor de pc met weegschaalsoftware. Bijvoorbeeld een Samba-share die
   alleen in het winkelnetwerk zichtbaar is, met een eigen wachtwoord per apparaat
   (EN 18031: geen standaardwachtwoord). Stel in de weegschaalsoftware in dat de export daarheen gaat.
3. **Eerste keer:** importeer één export via *Producten → importeren* (prijsbron *Webinterface*)
   en bevestig de kolommen. Zet daarna de prijsbron op *Kassa of weegschaal*.
4. Daarna verwerkt het basisstation elke nieuwe export binnen een halve minuut (zodra het bestand
   niet meer groeit). Het verplaatst het bestand naar `verwerkt/` of `fout/`, met een
   `.resultaat.txt` ernaast. De laatste import staat ook op de statuspagina.
5. Is de cloud tijdelijk onbereikbaar, dan blijft het bestand staan en volgt later een nieuwe poging.

## Installatie in de winkel

- Plafond- of wandmontage centraal boven de verkoopvloer; bij koelcellen/vitrines: zicht op de
  toonbank. Metalen vitrines en water/ijs dempen 2,4 GHz sterk → **sitesurvey** met testlabel
  (RSSI wordt per label gemeten en is zichtbaar in de monitoring).
- Bij voorkeur één PoE-kabel. Anders: netvoeding + Wi-Fi (bij voorkeur 5 GHz).
- Geen poorten open in de firewall nodig (alleen uitgaand 443).
