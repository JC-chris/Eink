# Eink — elektronische schaplabels voor versspeciaalzaken en supermarkten

Eigen systeem voor meerkleurige e-ink prijslabels voor slagerijen, viswinkels,
bakkers en supermarkten: **eigen labels (PCB + firmware), eigen basisstation
met zender, eigen cloudsoftware** die vanuit het kassasysteem wordt aangestuurd
en op afstand wordt gemonitord.

```
 Kassa / weegschaal ──REST/CSV──►  Cloud (eink_cloud)  ◄──HTTPS──  Basisstation  ──2,4 GHz──►  Labels
                                   • producten & prijzen          (Linux + nRF54L15)           (nRF54L15 + e-paper)
                                   • rendering → bitmap
                                   • update-jobs & retries
 Support / monitoring ◄────────────• monitoring, alerts, /metrics
```

## Inhoud van deze repository

| Map | Wat |
|---|---|
| [`docs/`](docs/) | Ontwerp: architectuur, hardware, basisstation, radioprotocol, kassa-API, monitoring, certificering, roadmap |
| [`backend/`](backend/) | Cloud-backend (Python/FastAPI): kassa-API, label-rendering, job-dispatch, monitoring & alerts, **managementsysteem** (`/beheer`, abonnementen, ondertekende licenties) — **werkend, met tests** |
| [`basestation/`](basestation/) | Agent + **lokale webinterface** op het basisstation (status, **Ethernet/Wi-Fi**, instellingen, prijzen beheren zonder kassa); inclusief **radio-simulator** zodat alles zonder hardware te testen is |
| [`firmware/`](firmware/) | Label-firmware: beeldformaat (C-header) en decoder; plan voor Zephyr/nRF Connect SDK |
| [`hardware/`](hardware/) | Eisen en blokschema's voor label-PCB en basisstation-PCB, eerste BOM-schatting |

## Documentatie (begin hier)

1. [Architectuur & keuzes](docs/01-architectuur.md)
2. [Label-hardware (PCB, display, batterij, behuizing)](docs/02-hardware-label.md)
3. [Basisstation met zender](docs/03-basisstation.md)
4. [Radioprotocol & beeldformaat](docs/04-radioprotocol.md)
5. [Kassa-integratie (API)](docs/05-kassa-integratie.md)
6. [Monitoring op afstand](docs/06-monitoring.md)
7. [Certificering & wetgeving](docs/07-certificering-en-wetgeving.md)
8. [Roadmap, team & kosten](docs/08-roadmap.md)
9. [Managementsysteem: scannen bij uitlevering, voorraad & koppelen, abonnementen, wekelijkse check-in](docs/09-managementsysteem.md)

## Snel starten (zonder hardware)

```bash
pip install -r backend/requirements.txt -r basestation/requirements.txt

# tests
python -m pytest backend/tests basestation/tests

# volledige demo: winkel aanmaken, basisstation, 3 labels, prijzen vanuit "kassa",
# gesimuleerde radio, monitoring-overzicht en PNG-previews in ./demo-output
python scripts/demo.py
```

Of als losse services:

```bash
# cloud
cd backend
export EINK_ADMIN_TOKEN=geheim EINK_LICENSE_KEY_FILE=./license_key.pem
python -m eink_cloud.cli create-operator anna --role admin   # account voor het managementsysteem
uvicorn eink_cloud.main:app --reload
# API-documentatie: http://localhost:8000/docs · managementsysteem: http://localhost:8000/beheer

# winkel + basisstation aanmaken (prijsbron "manual" = zonder kassa, via webinterface)
curl -XPOST localhost:8000/v1/admin/stores -H 'Authorization: Bearer geheim' -H 'content-type: application/json' \
     -d '{"id":"slagerij-jansen","name":"Slagerij Jansen","price_source":"manual"}'
curl -XPOST localhost:8000/v1/admin/stores/slagerij-jansen/basestations -H 'Authorization: Bearer geheim' \
     -H 'content-type: application/json' -d '{"id":"bs-1"}'          # → token

# basisstation met gesimuleerde labels; webinterface op http://localhost:8080
cd basestation && python -m eink_basestation.agent --config ./config.json \
     --server http://localhost:8000 --token <token> --simulate C0:FF:EE:00:00:01 C0:FF:EE:00:00:02
# het eerste wachtwoord van de webinterface staat in de log
```
