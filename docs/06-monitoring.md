# 6. Monitoring op afstand

Doel: **wij zien een storing eerder dan de winkel**.

## Wat wordt gemeten

| Bron | Metingen |
|---|---|
| Label | laatst gezien, batterijspanning, temperatuur, RSSI, firmwareversie, getoonde vs. verwachte CRC |
| Basisstation | laatst gezien (heartbeat), uptime, CPU-temperatuur, softwareversie, aantal gehoorde labels |
| Update-jobs | wachtend, verstuurd, gelukt, mislukt, aantal pogingen, doorlooptijd |

## Alertregels (geïmplementeerd in `backend/eink_cloud/monitoring.py`)

| Alert | Wanneer | Ernst |
|---|---|---|
| `basestation_offline` | geen heartbeat > 5 min | kritiek |
| `label_offline` | label > 6 uur niet gehoord | waarschuwing |
| `battery_low` | batterij < 2400 mV | waarschuwing |
| `update_failed` | update 3× mislukt | kritiek (verkeerde prijs op het schap!) |

Verstuurde jobs zonder antwoord binnen 10 minuten worden automatisch opnieuw ingepland.
Alerts sluiten zichzelf zodra het probleem weg is.

## Endpoints

- `GET /v1/monitoring/overview` — per winkel: labels online/offline, lege batterijen, wachtende en
  mislukte updates, status basisstations, open alerts.
- `GET /v1/monitoring/alerts?open=true`
- `GET /metrics` — **Prometheus**-formaat. Koppel aan Grafana voor dashboards en aan
  Alertmanager voor e-mail/SMS/Slack/PagerDuty bij kritieke alerts.

## Support-werkwijze

1. Alert komt binnen (Grafana/Alertmanager → support-kanaal).
2. Support opent de winkel in het overzicht, bekijkt de **preview** van het label en de telemetrie.
3. Op afstand: job opnieuw sturen, label laten knipperen (LED) zodat de winkel het label vindt,
   basisstation herstarten, remote tunnel openen, firmware-update uitrollen.
4. Pas daarna: winkel bellen of monteur sturen.

Ter plekke kan de winkel (of een monteur) dezelfde status zien in de **webinterface van het
basisstation** (zie [basisstation](03-basisstation.md#webinterface-lokaal-in-het-winkelnetwerk)).

## Later

- Batterij-voorspelling (trend in mV → "vervangen over ~3 maanden").
- Klantportaal met eigen status van de winkel.
- SLA-rapportage per maand.
