# 7. Certificering & wetgeving (EU / Nederland)

> Indicatief overzicht — laat dit valideren door een geaccrediteerd testlab (bv. Dekra, TÜV,
> Kiwa, Telefication) en plan het **vroeg**: certificering bepaalt mede het PCB-ontwerp.

## Verplicht voor CE-markering

| Richtlijn / norm | Wat | Geldt voor |
|---|---|---|
| **RED 2014/53/EU** | Radio-apparatuur | label + basisstation |
| EN 300 328 | 2,4 GHz radio (EN 300 220 bij 868 MHz) | label + basisstation |
| EN 301 489-1 / -17 | EMC radio-apparatuur | label + basisstation |
| EN 62368-1 | Elektrische veiligheid | basisstation (labels: beperkt) |
| EN 62311 / EN 50663 | Blootstelling RF (laag vermogen) | beide |
| **EN 18031-1** (RED gedelegeerde handeling cybersecurity) | Verplicht sinds 1 aug 2025 voor internet-verbonden radio-apparatuur: geen standaardwachtwoorden, veilige updates, beveiligde communicatie | basisstation (en labels via het systeem) |
| RoHS 2011/65/EU | Gevaarlijke stoffen | beide |
| WEEE | Inzameling/recycling, registratie bij Stichting OPEN | beide |
| **Batterijverordening (EU) 2023/1542** | Etikettering, inzameling, vervangbaarheid, registratie | label |

## Komt eraan

- **Cyber Resilience Act (EU) 2024/2847**: meldplicht voor actief misbruikte kwetsbaarheden
  vanaf **september 2026**, volledige eisen vanaf **december 2027** (SBOM, kwetsbaarhedenbeheer,
  security-updates gedurende de supportperiode). Bouw dit nu al in: gesigneerde firmware,
  SBOM per release, beveiligd OTA, vulnerability-disclosure-beleid.

## Bluetooth

Gebruik je BLE/ESL en het Bluetooth-logo/naam: **Bluetooth SIG-lidmaatschap + product listing**
(kosten per ontwerp). Met een voorgecertificeerde module is een groot deel van de RF-tests al
afgedekt.

## Overig

- **Besluit prijsaanduiding producten**: eenheidsprijs verplicht (zie kassa-integratie).
- **AVG**: het systeem verwerkt nauwelijks persoonsgegevens; wel verwerkersovereenkomst met
  winkels voor gebruikers-accounts en logs.
- Hygiëne/HACCP: geen certificering voor het label zelf, maar materiaalkeuze en reinigbaarheid
  zijn een verkoopargument voor versspeciaalzaken.
