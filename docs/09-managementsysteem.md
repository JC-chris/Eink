# 9. Managementsysteem, abonnementen en verbindingslaag

## Overzicht

```
 Facturatie / CRM ──REST (X-Actor)──►  /v1/manage/...  ┐
 Onze medewerkers ──browser─────────►  /beheer         ├─ Cloud (managementsysteem)
                                                       │   • klanten + abonnementen
 Basisstation ──check-in (heartbeat)──► licentie ◄─────┘   • monitoring + storingen
     ▲                                  (Ed25519, 7 dagen)  • auditlog
     └── stopt zonder geldige licentie
```

## Beheer-webinterface (`/beheer`)

| Pagina | Wat |
|---|---|
| **Dashboard** | Klanten per status, maandomzet (MRR), basisstations online, gemiste wekelijkse check-ins, labels online/batterij/niet actueel, open storingen, opzeggingen die binnenkort ingaan |
| **Klanten** | Zoeken, nieuwe klant met pakket en maandprijs |
| **Klant** | Gegevens en abonnement, **opzegging registreren** (met einddatum), **opzegging intrekken**, **direct uitschakelen**, **heractiveren**, winkels toevoegen, auditlog van de klant |
| **Winkel** | Labels (status, batterij, signaal), basisstations met licentiestatus, storingen, basisstation toevoegen (token wordt één keer getoond), nieuwe kassa-API-sleutel |
| **Basisstations** | Alle basisstations met laatste check-in en hoe lang de licentie nog geldig is |
| **Voorraad** | Labels en basisstations die nog niet gekoppeld zijn; op voorraad zetten (plaklijst/CSV/scanner), selecteren en aan een winkel koppelen, zoeken op label-ID |
| **Storingen** | Open en recent opgeloste storingen |
| **Auditlog** | Wie heeft wanneer wat gedaan (medewerker of extern systeem) |
| **Medewerkers** | Accounts beheren (alleen admin) |

**Rollen.** `admin` mag klanten, contracten, winkels en basisstations beheren. `support` kan
alles bekijken en storingen oplossen (labels opnieuw versturen), maar komt niet aan contracten.

Eerste admin aanmaken op de server:

```bash
EINK_DATABASE_URL=... python -m eink_cloud.cli create-operator anna --role admin
```

## Displays en basisstations koppelen aan klant/winkel

```
 fabriek ──► VOORRAAD ──koppelen──► WINKEL (van een KLANT) ──► vast of automatisch BASISSTATION
                ▲                        │
                └──── naar voorraad ─────┘   (retour, defect, vervanging)
```

1. **Op voorraad zetten**: de fabriek levert een lijst label-ID's met displaytype (CSV of
   scanner). Plak die in *Voorraad*, of gebruik `POST /v1/manage/labels`. Basisstations gaan ook op
   voorraad; hun token gaat in de fabrieksconfig.
2. **Koppelen aan winkel** (en daarmee aan de klant): selecteer labels in *Voorraad*, of plak de
   ID's op de winkelpagina. Een basisstation koppel je aan een winkel vanuit *Voorraad*. Een
   basisstation op voorraad krijgt geen licentie en doet niets.
3. **Basisstation per label**:
   - *Automatisch* (standaard): updates gaan via het basisstation dat het label het laatst hoorde.
   - *Vast*: alleen via het gekozen basisstation, bijvoorbeeld een apart basisstation voor de
     koelcel, of om storing tussen twee basisstations te voorkomen. Dit kan per label op de
     winkelpagina, of bij het koppelen voor een hele reeks tegelijk.
4. **Gehoord, niet gekoppeld**: elk basisstation meldt ook labels die het hoort maar die niet bij
   zijn winkel horen. De winkelpagina toont die met hun status:
   - *voorraad*: koppelen met één klik;
   - *onbekend*: displaytype kiezen, dan op voorraad zetten en koppelen;
   - *hoort bij een andere winkel*: alleen een admin kan het label hierheen verplaatsen.
     Telemetrie van labels van de buren wordt niet overgenomen.
5. **Ontkoppelen**: *Naar voorraad* haalt het label weg bij de winkel. Productkoppeling, vaste
   koppeling en openstaande updates vervallen. Een basisstation verplaatsen naar een andere winkel
   of klant kan ook. Labels die er vast aan hingen gaan dan terug naar automatisch.
6. Alles komt in het **auditlog**.

**Zelf registreren door de winkel** (kassa-API of de webinterface van het basisstation):

| Label is… | Mag de winkel het registreren? |
|---|---|
| al van deze winkel | ja (displaytype bijwerken) |
| van een andere winkel | nee (409) |
| op voorraad | alleen als een basisstation van deze winkel het in de afgelopen 24 uur gehoord heeft. Dat bewijst dat het label fysiek in de winkel is. Het displaytype komt uit de voorraad |
| onbekend | ja in ontwikkeling; in productie uit te zetten met `EINK_REQUIRE_INVENTORY=1` |

Management-API voor voorraad en koppelen:

| Methode | Pad | |
|---|---|---|
| GET | `/v1/manage/labels?stock=true` of `?store_id=` | Labels op voorraad / per winkel |
| POST | `/v1/manage/labels` | `{"label_ids": [...], "display_type": "bwry_2_9"}` op voorraad zetten |
| POST | `/v1/manage/labels/assign` | `{"label_ids": [...], "store_id": "...", "basestation_id": null, "move": false}` |
| POST | `/v1/manage/labels/unassign` | `{"label_ids": [...]}` terug naar voorraad |
| PUT | `/v1/manage/labels/{id}/basestation` | `{"basestation_id": "bs-..."}` vast, of `null` voor automatisch |
| GET | `/v1/manage/stores/{id}/sightings` | Gehoorde, niet-gekoppelde labels |
| POST | `/v1/manage/basestations` | Basisstation op voorraad (geeft token) |
| POST | `/v1/manage/basestations/{id}/assign` | `{"store_id": "..."}` koppelen/verplaatsen, `null` = voorraad |

## Abonnementen

```
  proefperiode / actief ──opzeggen (einddatum)──► opgezegd ──einddatum verstreken──► uitgeschakeld
           │                                        │                                   ▲
           └──────────── direct uitschakelen ───────┴───────────────────────────────────┘
  opgezegd ──intrekken──► actief            uitgeschakeld ──heractiveren──► actief
```

- **Opgezegd**: alles blijft werken tot en met de einddatum. De dag erna schakelt het systeem
  automatisch uit (de controle draait elke minuut).
- **Uitgeschakeld**:
  - de kassa-API en de webinterface van het basisstation weigeren prijswijzigingen (HTTP 403);
  - **alle labels krijgen "Prijs aan de kassa"**. Een label met een verouderde prijs is voor de
    winkel een juridisch risico (prijsaanduiding), een neutraal label niet;
  - storingsmeldingen voor die winkel stoppen;
  - de licentie van de basisstations krijgt status `suspended`.
- **Heractiveren**: labels krijgen direct weer hun actuele prijzen. Gegevens blijven bewaard.
- Elke actie komt in het **auditlog**, met medewerker of extern systeem en de reden.

## Verbindingslaag: wekelijkse check-in

Elk basisstation checkt elke 30 seconden in (heartbeat). Het antwoord bevat een **licentie** die de
cloud met een Ed25519-sleutel ondertekent:

```json
{"v":1, "basestation_id":"bs-jansen-1", "store_id":"jansen-1", "status":"active",
 "issued_at":1791400000, "valid_until":1792004800, "message":null, "support":"support@..."}
```

| Situatie | Gevolg op het basisstation |
|---|---|
| Normale check-ins | Licentie steeds 7 dagen vooruit geldig |
| Nog < 2 dagen geldig | Waarschuwing in de webinterface; in het managementsysteem alert `license_expiring` |
| **7 dagen geen verbinding** | Licentie verlopen: geen radioverkeer meer, melding in de webinterface; alert `license_expired`. Zodra de verbinding terug is, werkt alles direct weer |
| Abonnement uitgeschakeld | Status `suspended`: alleen nog de "Prijs aan de kassa"-beelden, prijsbeheer uit |
| Eigen server ingesteld | Handtekening klopt niet → licentie geweigerd |
| Licentie aangepast (geldigheid opgerekt) | Handtekening klopt niet → geweigerd |
| Licentie van ander basisstation gekopieerd | `basestation_id` klopt niet → geweigerd |
| Klok teruggezet | Gedetecteerd via de hoogst geziene tijd → ongeldig tot de volgende check-in |

De geldigheid telt vanaf het moment van ontvangst met de eigen klok. Een basisstation met een
afwijkende klok krijgt dus geen onterechte storing.

**Sleutelbeheer.** De privésleutel staat in `EINK_LICENSE_KEY_FILE` (productie: een secret
manager/HSM, nooit in git). De publieke sleutel zet de fabriek in de config van elk basisstation
(`license_public_key`). Zonder die waarde wordt hij bij de eerste verbinding vastgezet; dat is
alleen bedoeld voor ontwikkeling.

## Management-API (koppeling facturatie/CRM)

Authenticatie: `Authorization: Bearer <EINK_ADMIN_TOKEN>`. De header `X-Actor: facturatie` geeft
aan wie de wijziging doet (komt in het auditlog).

| Methode | Pad | |
|---|---|---|
| GET/POST | `/v1/manage/customers` | Klanten opvragen / aanmaken |
| GET/PUT | `/v1/manage/customers/{id}` | Klant opvragen / gegevens, pakket en prijs wijzigen |
| POST | `/v1/manage/customers/{id}/cancel` | `{"end_date": "2026-12-31"}` opzegging registreren |
| POST | `/v1/manage/customers/{id}/revoke-cancellation` | Opzegging intrekken |
| POST | `/v1/manage/customers/{id}/suspend` | `{"reason": "..."}` direct uitschakelen |
| POST | `/v1/manage/customers/{id}/reactivate` | Heractiveren |
| GET | `/v1/manage/basestations` | Alle basisstations met laatste check-in en licentie |
| GET | `/v1/manage/audit?customer_id=` | Auditlog |
| POST | `/v1/admin/stores` | Winkel aanmaken, met `customer_id` |

Typische koppeling: het facturatiesysteem roept bij een opzegging `cancel` aan met het einde van
de looptijd. Bij een herhaalde wanbetaling volgt `suspend`, na betaling `reactivate`.

## Contract en zorgvuldigheid

- Leg in de **algemene voorwaarden** vast dat de dienst een abonnement is: het systeem stopt aan
  het einde van de looptijd, het basisstation moet wekelijks verbinding maken, en labels tonen na
  beëindiging een neutraal beeld. Zo is er geen discussie bij uitschakeling.
- Waarschuw de klant vooraf: het managementsysteem toont lopende opzeggingen, en het basisstation
  toont de einddatum in zijn webinterface.
- Geef bij beëindiging de mogelijkheid de eigen productgegevens te exporteren (nog te bouwen).
- Wie hardware koopt in plaats van huurt, heeft andere rechten. Maak in het contract duidelijk of
  de hardware in bruikleen is. Laat dit juridisch toetsen.
