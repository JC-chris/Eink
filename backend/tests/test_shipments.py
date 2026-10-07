"""Scannen bij uitlevering: basisstation + displays in één keer aan de klant koppelen."""

import pytest
from fastapi.testclient import TestClient

from eink_cloud.inventory import parse_scan
from eink_cloud.models import Operator
from eink_cloud.security import hash_password

ADMIN = "admin-test-token"  # zelfde als conftest


@pytest.fixture
def m(app, admin):
    m = TestClient(app, headers={"Authorization": f"Bearer {ADMIN}", "X-Actor": "magazijn"})
    m.post("/v1/manage/customers", json={"id": "jansen", "name": "Slagerij Jansen"})
    m.post("/v1/manage/customers", json={"id": "buur", "name": "Bakker Buur"})
    admin.post("/v1/admin/stores", json={"id": "jansen-1", "name": "Jansen", "customer_id": "jansen"})
    admin.post("/v1/admin/stores", json={"id": "buur-1", "name": "Buur", "customer_id": "buur"})
    m.post("/v1/manage/basestations", json={"id": "bs-0042"})
    m.post("/v1/manage/basestations", json={"id": "bs-0043"})
    m.post("/v1/manage/labels", json={"label_ids": ["C0:FF:EE:00:00:01", "C0:FF:EE:00:00:02"], "display_type": "bwry_4_2"})
    m.post("/v1/manage/labels", json={"label_ids": ["C0:FF:EE:00:00:09"], "display_type": "bwry_2_9"})
    m.post("/v1/manage/labels/assign", json={"label_ids": ["C0:FF:EE:00:00:09"], "store_id": "buur-1"})
    return m


def test_parse_scan_formats(app, m):
    with app.state.sessionmaker() as s:
        assert parse_scan(s, "B:bs-0042") == ("basestation", "bs-0042")
        assert parse_scan(s, "EINK:B:bs-0042") == ("basestation", "bs-0042")
        assert parse_scan(s, "bs-0042") == ("basestation", "bs-0042")  # bekend basisstation zonder voorvoegsel
        assert parse_scan(s, "L:c0ffee000001") == ("label", "C0:FF:EE:00:00:01")
        assert parse_scan(s, "eink:l:C0-FF-EE-00-00-01") == ("label", "C0:FF:EE:00:00:01")
        assert parse_scan(s, " c0ffee000001 ") == ("label", "C0:FF:EE:00:00:01")


def test_scan_check_statuses(m):
    def check(code, store="jansen-1"):
        return m.get("/v1/manage/scan-check", params={"store_id": store, "code": code}).json()
    assert check("B:bs-0042")["status"] == "ok"
    assert check("B:bs-9999")["status"] == "error"
    r = check("c0ffee000001")
    assert r["status"] == "ok" and r["display_type"] == "bwry_4_2" and "4,2" in r["message"]
    r = check("C0:FF:EE:00:00:77")
    assert r["status"] == "ok" and r["new"] is True
    assert check("C0:FF:EE:00:00:09")["status"] == "error"  # van de buren
    assert check("C0:FF:EE:00:00:09", "buur-1")["status"] == "warn"  # al van deze winkel
    assert check("hallo")["status"] == "error"


def test_new_order_basestation_plus_displays(app, m):
    r = m.post("/v1/manage/shipments", json={
        "store_id": "jansen-1", "reference": "ORD-1",
        "codes": ["B:bs-0042", "L:C0FFEE000001", "C0:FF:EE:00:00:02", "c0ffee000077", "C0:FF:EE:00:00:02"]})
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["basestation_id"] == "bs-0042" and s["pinned"] and s["customer_id"] == "jansen"
    assert s["label_ids"] == ["C0:FF:EE:00:00:01", "C0:FF:EE:00:00:02", "C0:FF:EE:00:00:77"]

    labels = {l["id"]: l for l in m.get("/v1/manage/labels", params={"store_id": "jansen-1"}).json()}
    assert set(labels) == set(s["label_ids"])
    assert all(l["pinned_basestation_id"] == "bs-0042" for l in labels.values())
    assert labels["C0:FF:EE:00:00:77"]["display_type"] == "bwry_2_9"  # nieuw, standaardtype
    bs = {b["id"]: b for b in m.get("/v1/manage/basestations").json()}
    assert bs["bs-0042"]["store_id"] == "jansen-1" and bs["bs-0042"]["customer_id"] == "jansen"
    assert "shipment_created" in [e["action"] for e in m.get("/v1/manage/audit", params={"customer_id": "jansen"}).json()]

    # Uitbreiding: alleen nieuwe displays scannen; die komen bij dezelfde klant (automatisch basisstation).
    r = m.post("/v1/manage/shipments", json={"store_id": "jansen-1", "codes": ["C0:FF:EE:00:01:00", "C0:FF:EE:00:01:01"],
                                             "new_display_type": "spectra6_7_3"})
    s2 = r.json()
    assert s2["basestation_id"] is None and not s2["pinned"] and len(s2["label_ids"]) == 2
    assert [x["id"] for x in m.get("/v1/manage/shipments", params={"customer_id": "jansen"}).json()] == [s2["id"], s["id"]]


def test_shipment_is_all_or_nothing(m):
    r = m.post("/v1/manage/shipments", json={"store_id": "jansen-1", "codes": ["B:bs-0042", "C0:FF:EE:00:00:01",
                                                                              "C0:FF:EE:00:00:09"]})
    assert r.status_code == 409 and "buur-1" in r.json()["detail"]
    assert {b["id"]: b for b in m.get("/v1/manage/basestations").json()}["bs-0042"]["store_id"] is None
    assert m.get("/v1/manage/labels", params={"store_id": "jansen-1"}).json() == []

    r = m.post("/v1/manage/shipments", json={"store_id": "jansen-1", "codes": ["B:bs-0042", "B:bs-0043"]})
    assert r.status_code == 409 and "één basisstation" in r.json()["detail"]


def test_unpinned_option_and_station_works_after_delivery(app, m):
    m.post("/v1/manage/shipments", json={"store_id": "jansen-1", "codes": ["B:bs-0043", "C0:FF:EE:00:00:01"], "pin": False})
    assert m.get("/v1/manage/labels", params={"store_id": "jansen-1"}).json()[0]["pinned_basestation_id"] is None
    token = m.post("/v1/manage/basestations", json={"id": "bs-0050"}).json()["token"]
    m.post("/v1/manage/shipments", json={"store_id": "jansen-1", "codes": ["bs-0050"]})
    station = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    assert station.post("/v1/basestation/heartbeat", json={"software_version": "t", "uptime_s": 1}).status_code == 200


def test_scan_web_interface(app, m):
    with app.state.sessionmaker() as session:
        session.add(Operator(username="sam", password_hash=hash_password("sam-wachtwoord"), role="support"))
        session.commit()
    ui = TestClient(app)
    ui.post("/beheer/login", data={"username": "sam", "password": "sam-wachtwoord"})
    assert "Slagerij Jansen — Jansen" in ui.get("/beheer/scannen").text
    page = ui.get("/beheer/scannen", params={"store_id": "jansen-1"}).text
    assert 'id="scan"' in page and "Levering voor Jansen" in page
    r = ui.get("/beheer/scannen/controle", params={"store_id": "jansen-1", "code": "B:bs-0042"})
    assert r.json()["status"] == "ok"

    r = ui.post("/beheer/scannen", data={"store_id": "jansen-1", "code": ["B:bs-0042", "C0:FF:EE:00:00:09"]})
    assert "hoort bij winkel buur-1" in r.text and "/beheer/scannen" in str(r.url)
    r = ui.post("/beheer/scannen", data={"store_id": "jansen-1", "code": ["B:bs-0042", "C0:FF:EE:00:00:01"],
                                         "codes_text": "C0:FF:EE:00:00:02\n", "pin": "1", "reference": "ORD-7"})
    assert "Pakbon — levering #" in r.text and "ORD-7" in r.text and "C0:FF:EE:00:00:02" in r.text
    assert "2" in r.text and "vast gekoppeld aan basisstation bs-0042" in r.text
    assert "ORD-7" in ui.get("/beheer/leveringen").text
    assert "Pakbon" in ui.get("/beheer/klanten/jansen").text
