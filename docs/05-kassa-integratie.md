# 5. Kassa-integratie

Volledige, interactieve API-documentatie: start de backend en open `/docs` (OpenAPI/Swagger).

## Authenticatie

Elke winkel krijgt een API-sleutel. De kassa stuurt die mee als
`Authorization: Bearer <winkel-api-sleutel>`.

## Prijs/product bijwerken (het belangrijkste endpoint)

```http
PUT /v1/stores/slagerij-jansen/products/1001
Authorization: Bearer <sleutel>
Content-Type: application/json

{
  "name": "Runderbiefstuk",
  "price_cents": 1295,
  "unit": "kg",
  "unit_price_cents": 3495,
  "origin": "Nederland",
  "promo_text": "Weekaanbieding"
}
```

Alle labels die aan SKU `1001` gekoppeld zijn worden automatisch opnieuw gerenderd en verstuurd.
Ongewijzigde producten veroorzaken géén radioverkeer (de CRC is dan gelijk) — dat spaart batterij,
dus de kassa mag gerust periodiek alles opnieuw sturen.

Staat de winkel op prijsbron **webinterface** (zie [basisstation](03-basisstation.md#webinterface-lokaal-in-het-winkelnetwerk)),
dan antwoordt dit endpoint met **409 Conflict**: de prijzen worden dan in de winkel zelf beheerd.
De huidige modus is op te vragen met `GET /v1/stores/{winkel}` (`price_source`: `pos` of `manual`).

## Bulk (bv. elke ochtend of na prijswijziging in de weegschaal)

```http
POST /v1/stores/slagerij-jansen/products:batch
[{ "sku": "1001", "name": "...", "price_cents": 1295, "unit": "kg" }, ...]
```

## Prijslijst importeren (CSV / Excel)

Voor winkels zonder API-koppeling. Denk aan de export uit weegschaal- of kassasoftware, of een
Excel-lijst die de winkel zelf bijhoudt.

```
PLU;Omschrijving;Prijs;Eenheid;Herkomst;Actie
1001;Runderbiefstuk;29,95;kg;Nederland;Weekaanbieding
2001;Slavink;1,85;st;;
```

- **Formaten:** CSV (puntkomma, komma, tab of `|`; UTF-8 of Windows-tekenset) en Excel (.xlsx,
  eerste werkblad). Oud .xls niet: sla dat op als .xlsx.
- **Kolommen** worden herkend op naam:
  - artikelnummer: *PLU, artikelnummer, art.nr, code, EAN*;
  - naam: *omschrijving, naam, artikel*;
  - prijs: *prijs, verkoopprijs, VK prijs*;
  - verder: eenheid, prijs per kg, herkomst, actie.

  Wordt een kolom niet herkend, dan kies je hem zelf. Na een geslaagde import wordt die indeling
  **per winkel bewaard**, zodat dezelfde export daarna vanzelf goed gaat.
- **Prijzen** mogen als `29,95`, `€ 1.234,50` of `29.95`. Eenheid: `kg`, `st`/`stuk`, `100g`, `l`,
  `pak`, of ja/nee bij een kolom "weegartikel".
- **Eerst controleren, dan importeren.** Het voorbeeld toont fouten per regelnummer. Zolang er
  fouten zijn, wordt **niets** ingelezen (alles of niets). Bestaande producten worden bijgewerkt,
  nieuwe toegevoegd; alleen labels waarvan de prijs echt verandert, krijgen een update.

Waar kan het:

| Waar | Wie | Prijsbron |
|---|---|---|
| Webinterface basisstation → *Producten* → *importeren* | winkel | Webinterface |
| **Importmap** op het basisstation (automatisch, zie [basisstation](03-basisstation.md#importmap-voor-exports-van-weegschaal-of-kassa)) | weegschaal-/kassasoftware | Kassa of weegschaal |
| Managementsysteem → winkel → *Prijslijst importeren* | onze support / installatie | elke |
| API `POST /v1/stores/{winkel}/products:import` (`filename`, `content_b64`, `dry_run`, optioneel `mapping`) | dealer, scriptje op de winkel-pc | Kassa |

**Nog niet:** producten die niet meer in de lijst staan, worden niet verwijderd. Merkspecifieke
formaten (bijvoorbeeld XML uit Mettler Toledo RetailSuite) komen erbij zodra er voorbeeldbestanden
zijn. Ze gebruiken dezelfde importstappen.

## Labels koppelen

```http
POST /v1/stores/slagerij-jansen/labels          {"label_id": "C0:FF:EE:00:00:01", "display_type": "bwry_2_9"}
PUT  /v1/stores/slagerij-jansen/labels/C0:FF:EE:00:00:01/product   {"sku": "1001"}
GET  /v1/stores/slagerij-jansen/labels/C0:FF:EE:00:00:01            → status incl. displayed/expected CRC
GET  /v1/stores/slagerij-jansen/labels/C0:FF:EE:00:00:01/preview.png → exact beeld van het label
```

## Koppelvarianten per type klant

| Klant | Hoe |
|---|---|
| Moderne kassa (Lightspeed, Shopify POS, eigen kassa) | Direct de REST-API, of een kleine connector die hun webhook ("product gewijzigd") vertaalt naar `PUT /products/{sku}` |
| Slager/bakker met **weegschaal-kassa** (Bizerba, Mettler Toledo, Dibal, Digi, Avery Berkel) | Weegschaalsoftware exporteert de PLU-lijst als CSV/Excel naar de **importmap** van het basisstation. Eerste keer de kolomindeling bevestigen, daarna automatisch. XML-formaten per merk volgen met voorbeeldbestanden |
| Supermarkt met ERP/HQ-prijzen | Nachtelijke batch + losse updates bij acties |
| Geen koppeling | **Webinterface op het basisstation** (prijsbron *webinterface*): winkel beheert zelf producten en prijzen, met de hand of met een Excel/CSV-upload |

## Prijsaanduiding (wettelijk)

Het **Besluit prijsaanduiding producten** verplicht naast de verkoopprijs de **eenheidsprijs**
(per kg/liter) bij producten per gewicht. De renderer toont daarom altijd `unit_price_cents`
als die is opgegeven, en bij `unit = "kg"` is de prijs zelf de kiloprijs. Laat de kassa altijd de
eenheidsprijs meesturen bij voorverpakte producten.

## Fase 2 (gepland)

- Webhooks terug naar de kassa: `label.update_failed`, `label.offline`.
- Template-editor per winkel (logo, lettertypen, allergenen, QR-code naar herkomst).
- Lokale API op het basisstation voor prijswijzigingen tijdens internetstoring.
