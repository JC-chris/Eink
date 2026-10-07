# eink_cloud — backend

```bash
pip install -r requirements.txt
EINK_ADMIN_TOKEN=geheim uvicorn eink_cloud.main:app --reload     # vanuit backend/
```

| Variabele | Standaard | |
|---|---|---|
| `EINK_ADMIN_TOKEN` | — (verplicht) | Token voor beheer- en monitoring-endpoints |
| `EINK_DATABASE_URL` | `sqlite:///eink.db` | Productie: `postgresql+psycopg://...` |
| `EINK_LICENSE_KEY_FILE` | — (tijdelijke sleutel) | Ed25519-sleutel voor licenties; wordt aangemaakt als het bestand niet bestaat. **Bewaren en back-uppen** |
| `EINK_SESSION_SECRET` | afgeleid van admin-token | Ondertekening sessies managementsysteem |
| `EINK_REQUIRE_INVENTORY` | uit | `1` = winkels kunnen alleen labels uit onze voorraad registreren |
| `EINK_SUPPORT_CONTACT` | `support@example.com` | Contact dat basisstations tonen bij problemen |

Modules:

| Bestand | Rol |
|---|---|
| `api/pos.py` | Kassa-API: producten, labels koppelen, preview |
| `api/basestation.py` | Heartbeat, jobs ophalen, resultaten |
| `api/admin.py` | Winkels en basisstations aanmaken |
| `api/monitoring.py` | Overzicht, alerts, `/metrics` (Prometheus) |
| `api/manage.py` | Management-API voor facturatie/CRM |
| `api/beheer.py` + `templates/beheer/` | Webinterface managementsysteem (`/beheer`) |
| `inventory.py` | Voorraad, labels/basisstations koppelen aan winkel, vast basisstation, gehoorde labels |
| `subscriptions.py` | Abonnementen: opzeggen, uitschakelen, heractiveren, auditlog |
| `licensing.py` | Ondertekende licenties voor de wekelijkse check-in |
| `management.py` | Dashboard en gedeelde beheerlogica |
| `cli.py` | `create-operator` |
| `render.py` | Product → bitmap in het palet van het display |
| `imageformat.py` | Frameformaat naar het label (RLE + CRC32) |
| `jobs.py` | Jobs plannen, vervangen, retries |
| `monitoring.py` | Alertregels |
| `displays.py` | Catalogus displaytypes en paletten |

Volgende stappen: Alembic-migraties, PostgreSQL, gebruikersaccounts/portaal, webhooks naar de kassa,
PLU-import voor weegschalen, template-editor.
