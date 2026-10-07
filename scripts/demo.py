"""End-to-end demo zonder hardware: kassa → cloud → basisstation → gesimuleerde labels.

    python scripts/demo.py
"""

import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "basestation")]

from fastapi.testclient import TestClient  # noqa: E402

from eink_basestation.agent import Agent  # noqa: E402
from eink_basestation.radio import SimulatedRadio  # noqa: E402
from eink_cloud.main import create_app  # noqa: E402
from eink_cloud.models import utcnow  # noqa: E402
from eink_cloud.monitoring import evaluate_alerts  # noqa: E402

OUT = ROOT / "demo-output"
LABELS = {
    "C0:FF:EE:00:00:01": ("bwry_2_9", "1001"),
    "C0:FF:EE:00:00:02": ("bwr_2_13", "2001"),
    "C0:FF:EE:00:00:03": ("bwry_4_2", "3001"),
    "C0:FF:EE:00:00:04": ("spectra6_7_3", "1001"),
}
PRODUCTS = [
    {"sku": "1001", "name": "Runderbiefstuk", "price_cents": 2995, "unit": "kg", "origin": "Nederland", "promo_text": "Weekaanbieding"},
    {"sku": "2001", "name": "Kibbeling", "price_cents": 650, "unit": "st", "unit_price_cents": 1625, "origin": "Noordzee"},
    {"sku": "3001", "name": "Desembrood volkoren", "price_cents": 445, "unit": "st", "origin": "Eigen bakkerij"},
]


def step(text):
    print(f"\n== {text}")


def main():
    OUT.mkdir(exist_ok=True)
    app = create_app("sqlite://", "demo-admin", monitor_interval_s=None)
    admin = TestClient(app, headers={"Authorization": "Bearer demo-admin"})

    step("Winkel en basisstation aanmaken (beheer)")
    store = admin.post("/v1/admin/stores", json={"id": "versmarkt-demo", "name": "Versmarkt Demo"}).json()
    bs = admin.post("/v1/admin/stores/versmarkt-demo/basestations", json={"id": "bs-demo-1"}).json()
    pos = TestClient(app, headers={"Authorization": f"Bearer {store['api_key']}"})
    print(f"winkel-API-sleutel voor de kassa: {store['api_key'][:8]}…")

    step("Labels registreren en koppelen (app/kassa)")
    radio = SimulatedRadio()
    for label_id, (display, _) in LABELS.items():
        pos.post("/v1/stores/versmarkt-demo/labels", json={"label_id": label_id, "display_type": display})
        radio.add_label(label_id)
    r = pos.post("/v1/stores/versmarkt-demo/products:batch", json=PRODUCTS).json()
    for label_id, (_, sku) in LABELS.items():
        pos.put(f"/v1/stores/versmarkt-demo/labels/{label_id}/product", json={"sku": sku})

    step("Basisstation verwerkt de wachtrij")
    agent = Agent(TestClient(app, headers={"Authorization": f"Bearer {bs['token']}"}), radio)
    print(f"{agent.run_once()} labels bijgewerkt")

    step("Kassa wijzigt prijs biefstuk → beide gekoppelde labels")
    r = pos.put("/v1/stores/versmarkt-demo/products/1001", json={**PRODUCTS[0], "price_cents": 2795}).json()
    print(f"{r['labels_scheduled']} labels ingepland, {agent.process_jobs()} verstuurd")

    for label_id in LABELS:
        png = pos.get(f"/v1/stores/versmarkt-demo/labels/{label_id}/preview.png").content
        (OUT / f"{label_id.replace(':', '')}.png").write_bytes(png)
    print(f"previews opgeslagen in {OUT}/")

    step("Monitoring: storing simuleren (label buiten bereik, batterij bijna leeg)")
    radio.labels["C0:FF:EE:00:00:02"].status.battery_mv = 2350
    radio.labels["C0:FF:EE:00:00:03"].reachable = False
    agent.heartbeat()
    pos.put("/v1/stores/versmarkt-demo/products/3001", json={**PRODUCTS[2], "price_cents": 465})
    for _ in range(3):
        agent.process_jobs()
    with app.state.sessionmaker() as session:
        evaluate_alerts(session, utcnow() + timedelta(minutes=1))
    for a in admin.get("/v1/monitoring/alerts").json():
        print(f"[{a['severity']:8}] {a['kind']:20} {a['message']}")

    step("Overzicht voor support")
    print(json.dumps(admin.get("/v1/monitoring/overview").json(), indent=2, default=str))


if __name__ == "__main__":
    main()
