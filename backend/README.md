# eink_cloud — backend

```bash
pip install -r requirements.txt
EINK_ADMIN_TOKEN=geheim uvicorn eink_cloud.main:app --reload     # vanuit backend/
```

| Variabele | Standaard | |
|---|---|---|
| `EINK_ADMIN_TOKEN` | — (verplicht) | Token voor beheer- en monitoring-endpoints |
| `EINK_DATABASE_URL` | `sqlite:///eink.db` | Productie: `postgresql+psycopg://...` |

Modules:

| Bestand | Rol |
|---|---|
| `api/pos.py` | Kassa-API: producten, labels koppelen, preview |
| `api/basestation.py` | Heartbeat, jobs ophalen, resultaten |
| `api/admin.py` | Winkels en basisstations aanmaken |
| `api/monitoring.py` | Overzicht, alerts, `/metrics` (Prometheus) |
| `render.py` | Product → bitmap in het palet van het display |
| `imageformat.py` | Frameformaat naar het label (RLE + CRC32) |
| `jobs.py` | Jobs plannen, vervangen, retries |
| `monitoring.py` | Alertregels |
| `displays.py` | Catalogus displaytypes en paletten |

Volgende stappen: Alembic-migraties, PostgreSQL, gebruikersaccounts/portaal, webhooks naar de kassa,
PLU-import voor weegschalen, template-editor.
