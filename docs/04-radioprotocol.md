# 4. Radioprotocol & beeldformaat

## Radiolaag: Bluetooth LE ESL-profiel

Het **Electronic Shelf Label Profile / Service** (Bluetooth SIG, 2023) gebruikt
*Periodic Advertising with Responses* (PAwR):

- Het basisstation zendt periodiek (bv. elke 1–2 s) een sync-pakket; labels slapen daartussen.
- Labels zijn ingedeeld in **groepen** (max. 128) en hebben elk een ESL-ID; het basisstation
  kan per groep commando's sturen (`display image`, `LED aan`, `ping`, `factory reset`).
- Grote beeldbestanden gaan via een korte **BLE-verbinding** + Object Transfer Service (OTS),
  daarna gaat het label direct weer slapen.
- Beveiliging: per label een eigen sleutel (AES-CCM), uitgewisseld bij koppeling.

Nordic levert werkende voorbeelden in nRF Connect SDK (`samples/bluetooth/esl`) — **begin hier**.

## Koppelen (provisioning)

1. Label komt uit de fabriek met uniek ID (= BLE-adres) + QR-code + NFC-tag.
2. Medewerker scant met de beheer-app de QR/NFC van het label en de barcode van het product.
3. App roept `POST /v1/stores/{winkel}/labels` en `PUT .../labels/{id}/product` aan.
4. Basisstation ziet het label, voert ESL-bonding uit, en het eerste beeld wordt verstuurd.

## Beeldformaat (eigen, bovenop OTS)

De cloud levert per label een **frame**: 18-byte header + RLE-gecomprimeerde pixeldata.
Gedefinieerd in [`firmware/label/src/eink_image.h`](../firmware/label/src/eink_image.h)
en geïmplementeerd in [`backend/eink_cloud/imageformat.py`](../backend/eink_cloud/imageformat.py).

```
offset  size  veld
0       2     magic "EI"
2       1     versie (1)
3       1     encoding (1 = RLE)
4       2     breedte (LE)
6       2     hoogte  (LE)
8       1     bits per pixel (1, 2 of 4)
9       1     palette-ID (zie displays.py)
10      4     CRC32 van de ongecomprimeerde pixeldata
14      4     lengte van de gecomprimeerde data
18      n     RLE-data
```

- Pixels zijn **palet-indexen** (0 = zwart, 1 = wit, 2 = rood, 3 = geel, 4 = blauw, 5 = groen),
  rij voor rij, MSB-eerst gepakt. De firmware zet indexen om naar het panel-specifieke formaat.
- **RLE** (PackBits-variant): controlebyte `c`
  - `c & 0x80` → herhaal het volgende byte `(c & 0x7F) + 1` keer
  - anders → `c + 1` letterlijke bytes volgen
  Simpel genoeg voor een MCU, en prijslabels (veel wit vlak) comprimeren 5–20×.
- Na het tonen meldt het label de **CRC32** terug; de cloud weet daarmee zeker wat er op het
  label staat (belangrijk: verkeerde prijs op het schap = juridisch risico).

## Telemetrie van het label

Per sync/response: `battery_mv`, `temperature_c`, `rssi` (gemeten door basisstation),
`firmware_version`, `displayed_crc`. Dit voedt de monitoring.
