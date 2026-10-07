"""Volledige keten: kassa → cloud → basisstation-agent → (gesimuleerd) label."""

from datetime import timedelta

from eink_basestation.agent import Agent
from eink_basestation.radio import SimulatedRadio
from eink_cloud.models import utcnow
from eink_cloud.monitoring import evaluate_alerts

LABEL = "C0:FF:EE:00:00:01"
BIEFSTUK = {"name": "Runderbiefstuk", "price_cents": 1295, "unit": "kg", "origin": "Nederland"}


def setup_label(pos, sku="1001"):
    assert pos.post("/v1/stores/slagerij-jansen/labels", json={"label_id": LABEL, "display_type": "bwry_2_9"}).status_code == 201
    pos.put(f"/v1/stores/slagerij-jansen/products/{sku}", json=BIEFSTUK).raise_for_status()
    return pos.put(f"/v1/stores/slagerij-jansen/labels/{LABEL}/product", json={"sku": sku}).json()


def make_agent(station, **radio_kwargs):
    radio = SimulatedRadio(**radio_kwargs)
    radio.add_label(LABEL)
    return Agent(station, radio), radio


def test_price_update_reaches_label(store):
    pos, station = store
    label = setup_label(pos)
    assert label["in_sync"] is False and label["expected_crc"] is not None

    agent, radio = make_agent(station)
    assert agent.run_once() == 1
    label = pos.get(f"/v1/stores/slagerij-jansen/labels/{LABEL}").json()
    assert label["in_sync"] is True
    assert label["basestation_id"] == "bs-1"
    assert label["battery_mv"] == 2999

    # Zelfde prijs nogmaals sturen: geen nieuw radioverkeer.
    r = pos.put("/v1/stores/slagerij-jansen/products/1001", json=BIEFSTUK).json()
    assert r["labels_scheduled"] == 0
    assert agent.process_jobs() == 0

    # Prijswijziging: één nieuwe job, label daarna weer in sync met nieuwe CRC.
    r = pos.put("/v1/stores/slagerij-jansen/products/1001", json={**BIEFSTUK, "price_cents": 1395}).json()
    assert r["labels_scheduled"] == 1
    assert agent.process_jobs() == 1
    new = pos.get(f"/v1/stores/slagerij-jansen/labels/{LABEL}").json()
    assert new["in_sync"] and new["displayed_crc"] != label["displayed_crc"]


def test_rapid_updates_supersede_pending_jobs(store):
    pos, station = store
    setup_label(pos)
    for price in (1300, 1400, 1500):
        pos.put("/v1/stores/slagerij-jansen/products/1001", json={**BIEFSTUK, "price_cents": price})
    jobs = station.get("/v1/basestation/jobs").json()
    assert len(jobs) == 1  # alleen de laatste prijs gaat de lucht in


def test_batch_and_preview(store):
    pos, _ = store
    setup_label(pos)
    r = pos.post("/v1/stores/slagerij-jansen/products:batch", json=[
        {"sku": "1001", **BIEFSTUK, "price_cents": 999, "promo_text": "Actie"},
        {"sku": "2001", "name": "Kibbeling", "price_cents": 650},
    ])
    assert [x["labels_scheduled"] for x in r.json()] == [1, 0]
    png = pos.get(f"/v1/stores/slagerij-jansen/labels/{LABEL}/preview.png")
    assert png.headers["content-type"] == "image/png" and png.content[:4] == b"\x89PNG"


def test_failed_updates_retry_then_alert(store, admin):
    pos, station = store
    setup_label(pos)
    agent, radio = make_agent(station, failure_rate=1.0)
    agent.heartbeat()
    for _ in range(3):
        assert agent.process_jobs() == 1
    assert agent.process_jobs() == 0  # na 3 pogingen opgegeven

    alerts = admin.get("/v1/monitoring/alerts").json()
    assert [a["kind"] for a in alerts] == ["update_failed"]

    # Support forceert opnieuw, radio werkt weer → alert sluit zichzelf.
    radio.failure_rate = 0.0
    pos.post(f"/v1/stores/slagerij-jansen/labels/{LABEL}/refresh").raise_for_status()
    assert agent.process_jobs() == 1
    assert admin.get("/v1/monitoring/alerts").json() == []


def test_label_detecting_wrong_image_counts_as_failure(store):
    pos, station = store
    setup_label(pos)
    job = station.get("/v1/basestation/jobs").json()[0]
    r = station.post(f"/v1/basestation/jobs/{job['job_id']}/result", json={"success": True, "displayed_crc": 123})
    assert r.json()["status"] == "pending"


def test_monitoring_offline_and_battery(app, store, admin):
    pos, station = store
    setup_label(pos)
    agent, radio = make_agent(station)
    radio.labels[LABEL].status.battery_mv = 2300
    agent.run_once()

    with app.state.sessionmaker() as session:
        kinds = {a.kind for a in evaluate_alerts(session)}
        assert kinds == {"battery_low"}
        later = {a.kind for a in evaluate_alerts(session, utcnow() + timedelta(hours=7))}
        assert later == {"battery_low", "basestation_offline", "label_offline"}

    overview = admin.get("/v1/monitoring/overview").json()[0]
    assert overview["labels_total"] == 1 and overview["labels_online"] == 1
    assert overview["basestations"][0]["online"] is True
    metrics = admin.get("/metrics").text
    assert 'eink_labels_battery_low{store="slagerij-jansen"} 1' in metrics


def test_stale_sent_jobs_are_requeued(app, store):
    pos, station = store
    setup_label(pos)
    assert len(station.get("/v1/basestation/jobs").json()) == 1  # basisstation crasht hierna
    assert station.get("/v1/basestation/jobs").json() == []
    with app.state.sessionmaker() as session:
        evaluate_alerts(session, utcnow() + timedelta(minutes=11))
    assert len(station.get("/v1/basestation/jobs").json()) == 1


def test_auth(app, store, admin):
    from fastapi.testclient import TestClient

    pos, station = store
    other = admin.post("/v1/admin/stores", json={"id": "bakkerij-de-vries", "name": "Bakkerij"}).json()
    other_pos = TestClient(app, headers={"Authorization": f"Bearer {other['api_key']}"})
    assert other_pos.put("/v1/stores/slagerij-jansen/products/1", json=BIEFSTUK).status_code == 403
    assert TestClient(app).get("/v1/stores/slagerij-jansen/labels").status_code == 401
    assert pos.get("/v1/monitoring/overview").status_code == 403
    assert pos.get("/v1/basestation/jobs").status_code == 403
    assert pos.post("/v1/stores/slagerij-jansen/labels", json={"label_id": "x", "display_type": "nope"}).status_code == 422
