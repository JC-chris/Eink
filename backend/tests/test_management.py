"""Managementsysteem: abonnementen, uitschakelen, licenties en de beheer-webinterface."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from eink_basestation.license import verify
from eink_cloud.models import Operator, utcnow
from eink_cloud.monitoring import evaluate_alerts
from eink_cloud.security import hash_password

ADMIN = "admin-test-token"  # zelfde als conftest

LABEL = "C0:FF:EE:00:00:01"
PRODUCT = {"name": "Kabeljauwfilet", "price_cents": 2495, "unit": "kg"}


@pytest.fixture
def customer(app, admin):
    """Klant met één winkel, één basisstation en één gekoppeld label dat actueel is."""
    m = TestClient(app, headers={"Authorization": f"Bearer {ADMIN}", "X-Actor": "facturatie"})
    r = m.post("/v1/manage/customers", json={"id": "visser", "name": "Viswinkel Visser", "plan": "Standaard",
                                             "monthly_price_cents": 4900})
    assert r.status_code == 201 and r.json()["service_active"]
    store = admin.post("/v1/admin/stores", json={"id": "visser-markt", "name": "Visser Markt", "customer_id": "visser"}).json()
    bs = admin.post("/v1/admin/stores/visser-markt/basestations", json={"id": "bs-visser"}).json()
    pos = TestClient(app, headers={"Authorization": f"Bearer {store['api_key']}"})
    station = TestClient(app, headers={"Authorization": f"Bearer {bs['token']}"})
    pos.post("/v1/stores/visser-markt/labels", json={"label_id": LABEL, "display_type": "bwry_2_9"})
    pos.put("/v1/stores/visser-markt/products/1", json=PRODUCT)
    pos.put(f"/v1/stores/visser-markt/labels/{LABEL}/product", json={"sku": "1"})
    station.post("/v1/basestation/heartbeat", json={"software_version": "t", "uptime_s": 1})
    job = station.get("/v1/basestation/jobs").json()[0]
    station.post(f"/v1/basestation/jobs/{job['job_id']}/result", json={"success": True, "displayed_crc": job["crc32"]})
    return m, pos, station


def lease(station):
    r = station.post("/v1/basestation/heartbeat", json={"software_version": "t", "uptime_s": 1}).json()
    key = station.get("/v1/basestation/license-key").json()["public_key"]
    return verify(r["license"], key)


def test_heartbeat_returns_signed_weekly_license(customer):
    _m, _pos, station = customer
    p = lease(station)
    assert p["basestation_id"] == "bs-visser" and p["status"] == "active"
    assert p["valid_until"] - p["issued_at"] == 7 * 86400


def test_cancellation_runs_until_end_date_then_suspends(app, customer):
    m, pos, station = customer
    end = utcnow().date() + timedelta(days=30)
    c = m.post("/v1/manage/customers/visser/cancel", json={"end_date": end.isoformat()}).json()
    assert c["subscription_status"] == "cancelled" and c["service_active"]
    assert pos.put("/v1/stores/visser-markt/products/1", json={**PRODUCT, "price_cents": 2595}).status_code == 200
    assert "eindigt na" in lease(station)["message"]

    # Einddatum verstreken: monitoringronde schakelt automatisch uit.
    with app.state.sessionmaker() as session:
        evaluate_alerts(session, utcnow() + timedelta(days=31))
    assert pos.put("/v1/stores/visser-markt/products/1", json=PRODUCT).status_code == 403
    p = lease(station)
    assert p["status"] == "suspended" and "beëindigd" in p["message"]

    # Alle labels krijgen een neutraal beeld; prijsjobs gaan niet meer de lucht in.
    jobs = station.get("/v1/basestation/jobs").json()
    assert len(jobs) == 1
    label = pos.get(f"/v1/stores/visser-markt/labels/{LABEL}").json()
    assert label["expected_crc"] == jobs[0]["crc32"]


def test_cancel_in_past_and_revoke(customer):
    m, *_ = customer
    past = (utcnow().date() - timedelta(days=1)).isoformat()
    assert m.post("/v1/manage/customers/visser/cancel", json={"end_date": past}).status_code == 422
    m.post("/v1/manage/customers/visser/cancel", json={"end_date": "2099-01-31"})
    c = m.post("/v1/manage/customers/visser/revoke-cancellation").json()
    assert c["subscription_status"] == "active" and c["end_date"] is None


def test_suspend_and_reactivate(customer, admin):
    m, pos, station = customer
    assert m.post("/v1/manage/customers/visser/suspend", json={"reason": ""}).status_code == 422
    c = m.post("/v1/manage/customers/visser/suspend", json={"reason": "wanbetaling"}).json()
    assert c["subscription_status"] == "suspended" and c["suspend_reason"] == "wanbetaling"
    assert pos.post("/v1/stores/visser-markt/products:batch", json=[{"sku": "2", **PRODUCT}]).status_code == 403
    service_job = station.get("/v1/basestation/jobs").json()[0]
    station.post(f"/v1/basestation/jobs/{service_job['job_id']}/result",
                 json={"success": True, "displayed_crc": service_job["crc32"]})
    assert pos.post(f"/v1/stores/visser-markt/labels/{LABEL}/refresh").status_code == 403
    # Uitgeschakelde winkel geeft geen storingsmeldingen.
    assert admin.get("/v1/monitoring/alerts").json() == []

    c = m.post("/v1/manage/customers/visser/reactivate").json()
    assert c["service_active"] and c["subscription_status"] == "active"
    price_job = station.get("/v1/basestation/jobs").json()[0]
    assert price_job["crc32"] != service_job["crc32"]  # weer het prijsbeeld
    assert pos.put("/v1/stores/visser-markt/products/1", json=PRODUCT).status_code == 200

    actions = [(e["actor"], e["action"]) for e in m.get("/v1/manage/audit?customer_id=visser").json()]
    assert ("api:facturatie", "subscription_suspended") in actions
    assert ("api:facturatie", "subscription_reactivated") in actions
    assert ("api:facturatie", "store_suspended") in actions


def test_license_alerts(app, customer):
    with app.state.sessionmaker() as session:
        kinds = {a.kind for a in evaluate_alerts(session, utcnow() + timedelta(days=6))}
        assert "license_expiring" in kinds
        kinds = {a.kind for a in evaluate_alerts(session, utcnow() + timedelta(days=8))}
        assert "license_expired" in kinds and "license_expiring" not in kinds
    bs = customer[0].get("/v1/manage/basestations").json()[0]
    assert bs["customer_id"] == "visser" and bs["license_valid_until"] is not None


def test_management_api_requires_admin(customer):
    _m, pos, station = customer
    assert pos.get("/v1/manage/customers").status_code == 403
    assert station.post("/v1/manage/customers/visser/suspend", json={"reason": "x"}).status_code == 403


# --- beheer-webinterface ----------------------------------------------------------------------


@pytest.fixture
def operators(app):
    with app.state.sessionmaker() as session:
        session.add(Operator(username="anna", password_hash=hash_password("anna-wachtwoord"), role="admin"))
        session.add(Operator(username="sam", password_hash=hash_password("sam-wachtwoord"), role="support"))
        session.commit()


def ui_login(app, user, password):
    ui = TestClient(app)
    r = ui.post("/beheer/login", data={"username": user, "password": password}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return ui


def test_beheer_login_and_dashboard(app, customer, operators):
    anon = TestClient(app)
    assert anon.get("/beheer", follow_redirects=False).headers["location"] == "/beheer/login"
    assert "Onjuiste" in anon.post("/beheer/login", data={"username": "anna", "password": "fout"}).text
    ui = ui_login(app, "anna", "anna-wachtwoord")
    page = ui.get("/beheer").text
    assert "Maandomzet" in page and "€ 49,00" in page
    for path in ("/beheer/klanten", "/beheer/klanten/visser", "/beheer/winkels/visser-markt",
                 "/beheer/basisstations", "/beheer/storingen", "/beheer/audit", "/beheer/medewerkers"):
        assert ui.get(path).status_code == 200, path


def test_beheer_contract_flow(app, customer, operators):
    ui = ui_login(app, "anna", "anna-wachtwoord")
    r = ui.post("/beheer/klanten/visser/opzeggen", data={"end_date": "2099-12-31"})
    assert "de dienst stopt na 31-12-2099" in r.text and "opgezegd" in r.text
    r = ui.post("/beheer/klanten/visser/uitschakelen", data={"reason": "contract beëindigd", "confirm": "verkeerd"})
    assert "Typ ter bevestiging" in r.text
    r = ui.post("/beheer/klanten/visser/uitschakelen", data={"reason": "contract beëindigd", "confirm": "visser"})
    assert "Systeem uitgeschakeld" in r.text and "Heractiveren" in r.text
    assert "medewerker:anna" in ui.get("/beheer/audit").text
    r = ui.post("/beheer/klanten/visser/heractiveren")
    assert "weer actief" in r.text


def test_beheer_create_customer_store_basestation_shows_secret_once(app, operators):
    ui = ui_login(app, "anna", "anna-wachtwoord")
    r = ui.post("/beheer/klanten", data={"id": "bakker-bart", "name": "Bakkerij Bart", "monthly_price": "39,50"})
    assert "Klant Bakkerij Bart aangemaakt" in r.text and "€ 39,50" not in r.url.path
    r = ui.post("/beheer/klanten/bakker-bart/winkels", data={"store_id": "bart-dorp", "name": "Bart Dorp"})
    assert "API-sleutel voor de kassa" in r.text and "msg=" not in str(r.url)
    r = ui.post("/beheer/winkels/bart-dorp/basisstations", data={"bs_id": "bs-bart-1"})
    assert "Token voor basisstation bs-bart-1" in r.text
    # Daarna niet meer zichtbaar.
    assert "Token voor basisstation" not in ui.get("/beheer/winkels/bart-dorp").text
    r = ui.post("/beheer/klanten", data={"id": "Fout ID", "name": "x", "monthly_price": "1"})
    assert "flash err" in r.text


def test_beheer_support_role_cannot_change_contracts(app, customer, operators):
    ui = ui_login(app, "sam", "sam-wachtwoord")
    assert ui.get("/beheer/klanten/visser").status_code == 200
    assert ui.post("/beheer/klanten/visser/uitschakelen", data={"reason": "x", "confirm": "visser"}).status_code == 403
    assert ui.get("/beheer/medewerkers").status_code == 403
    r = ui.post(f"/beheer/winkels/visser-markt/labels/{LABEL}/opnieuw")
    assert "wordt opnieuw verstuurd" in r.text


def test_beheer_csrf(app, customer, operators):
    ui = ui_login(app, "anna", "anna-wachtwoord")
    r = ui.post("/beheer/klanten/visser/heractiveren", headers={"origin": "https://evil.example"})
    assert r.status_code == 403
