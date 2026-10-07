# eink_basestation — agent + webinterface

```bash
pip install -r requirements.txt
# gesimuleerde radio met twee labels; webinterface op http://localhost:8080
python -m eink_basestation.agent --config ./config.json --server http://localhost:8000 --token <token> \
    --simulate C0:FF:EE:00:00:01 C0:FF:EE:00:00:02
```

- Instellingen staan in `--config` (standaard `/etc/eink-basestation/config.json`, of `EINK_BASESTATION_CONFIG`).
  `--server`, `--token` en `--web-port` worden daarin opgeslagen; daarna kan alles via de webinterface.
- Bij de eerste start zonder wachtwoord wordt een uniek wachtwoord gegenereerd en in de log gezet.
- Zonder `--simulate` gebruikt de agent `NordicEslRadio` (nRF54L15 over UART) — die moet nog
  gebouwd worden, zie `eink_basestation/radio.py`.

| Bestand | Rol |
|---|---|
| `agent.py` | Heartbeat, jobs ophalen en via radio versturen; start ook de webinterface |
| `webui.py` + `templates/` | Lokale webinterface: status, producten, labels, instellingen |
| `cloud.py` | Client voor de cloud-API (met basisstation-token) |
| `config.py` | Instellingen + wachtwoordhashing |
| `radio.py` | `RadioBackend`, `SimulatedRadio`, `NordicEslRadio` (stub) |
