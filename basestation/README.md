# eink_basestation — agent

```bash
pip install -r requirements.txt
# met gesimuleerde radio en twee labels:
python -m eink_basestation.agent --server http://localhost:8000 --token <token> --simulate C0:FF:EE:00:00:01 C0:FF:EE:00:00:02
```

Zonder `--simulate` gebruikt de agent `NordicEslRadio` (nRF54L15 over UART) — die moet nog
gebouwd worden, zie `eink_basestation/radio.py`.
