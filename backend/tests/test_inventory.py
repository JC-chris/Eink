"""Voorraad en koppelen van labels en basisstations aan winkel/klant."""

import pytest
from fastapi.testclient import TestClient

from eink_cloud.models import Operator
from eink_cloud.security import hash_password

ADMIN = "admin-test-token"  # zelfde als conftest


@pytest.fixture
def setup(app, admin):
    m = TestClient(app, headers={"Authorization": f"Bearer {ADMIN}", "X-Actor": "magazijn"})
    m.post("/v1/manage/customers", json={"id": "jansen", "name": "Slagerij Jansen"})
    m.post("/v1/manage/customers", json={"id": "buur", "name": "Bakker Buur"})
    a = admin.post("/v1/admin/stores", json={"id": "jansen-1", "name": "Jansen", "customer_id": "jansen"}).json()
    b = admin.post("/v1/admin/stores", json={"id": "buur-1", "name": "Buur", "customer_id": "buur"}).json()
    bs1 = admin.post("/v1/admin/stores/jansen-1/basestations", json={"id": "bs-j1"}).json()
    bs2 = admin.post("/v1/admin/stores/jansen-1/basestations", json={"id": "bs-j2"}).json()
    bsb = admin.post("/v1/admin/stores/buur-1/basestations", json={"id": "bs-b1"}).json()
    c = lambda token: TestClient(app, headers={"Authorization": f"Bearer {token}"})  # noqa: E731
    return m, c(a["api_key"]), c(b["api_key"]), c(bs1["token"]), c(bs2["token"]), c(bsb["token"])


def hb(station, *labels, rssi=-60):
    r = station.post("/v1/basestation/heartbeat", json={"software_version": "t", "uptime_s": 1,
                     "labels_seen": [{"label_id": l, "rssi": rssi, "battery_mv": 3000} for l in labels]})
    assert r.status_code == 200, r.text


def test_stock_add_assign_unassign(setup, admin):
    m, pos, *_ = setup
    r = m.post("/v1/manage/labels", json={"label_ids": ["c0:ff:ee:00:00:01", "C0:FF:EE:00:00:02", " "], "display_type": "bwr_2_13"})
    assert r.json() == {"added": 2, "already_known": []}
    assert m.post("/v1/manage/labels", json={"label_ids": ["C0:FF:EE:00:00:01"], "display_type": "bwr_2_13"}).json()["already_known"] == ["C0:FF:EE:00:00:01"]
    assert len(m.get("/v1/manage/labels?stock=true").json()) == 2

    assert m.post("/v1/manage/labels/assign", json={"label_ids": ["C0:FF:EE:00:00:99"], "store_id": "jansen-1"}).status_code == 404
    assert m.post("/v1/manage/labels/assign", json={"label_ids": ["C0:FF:EE:00:00:01", "C0:FF:EE:00:00:02"],
                                                    "store_id": "jansen-1"}).json() == {"assigned": 2}
    labels = pos.get("/v1/stores/jansen-1/labels").json()
    assert [l["display_type"] for l in labels] == ["bwr_2_13", "bwr_2_13"]

    # Prijs koppelen, dan retour: product, jobs en koppeling weg.
    pos.put("/v1/stores/jansen-1/products/1", json={"name": "Worst", "price_cents": 199})
    pos.put("/v1/stores/jansen-1/labels/C0:FF:EE:00:00:01/product", json={"sku": "1"})
    assert m.post("/v1/manage/labels/unassign", json={"label_ids": ["C0:FF:EE:00:00:01"]}).json() == {"unassigned": 1}
    stock = {l["id"]: l for l in m.get("/v1/manage/labels?stock=true").json()}
    assert "C0:FF:EE:00:00:01" in stock and stock["C0:FF:EE:00:00:01"]["store_id"] is None
    assert pos.get("/v1/stores/jansen-1/labels/C0:FF:EE:00:00:01").status_code == 404
    actions = [e["action"] for e in m.get("/v1/manage/audit").json()]
    assert {"labels_to_stock", "labels_assigned", "label_to_stock"} <= set(actions)


def test_move_between_customers_requires_flag(setup):
    m, pos, pos_b, *_ = setup
    m.post("/v1/manage/labels", json={"label_ids": ["L1"], "display_type": "bwry_2_9"})
    m.post("/v1/manage/labels/assign", json={"label_ids": ["L1"], "store_id": "jansen-1"})
    r = m.post("/v1/manage/labels/assign", json={"label_ids": ["L1"], "store_id": "buur-1"})
    assert r.status_code == 409 and "andere winkel" in r.json()["detail"]
    assert m.post("/v1/manage/labels/assign", json={"label_ids": ["L1"], "store_id": "buur-1", "move": True}).status_code == 200
    assert pos_b.get("/v1/stores/buur-1/labels/L1").status_code == 200
    assert pos.get("/v1/stores/jansen-1/labels/L1").status_code == 404


def test_pinned_basestation_routes_jobs(setup):
    m, pos, _pb, st1, st2, stb = setup
    m.post("/v1/manage/labels", json={"label_ids": ["L1"], "display_type": "bwry_2_9"})
    assert m.post("/v1/manage/labels/assign", json={"label_ids": ["L1"], "store_id": "jansen-1",
                                                    "basestation_id": "bs-b1"}).status_code == 409  # andere winkel
    m.post("/v1/manage/labels/assign", json={"label_ids": ["L1"], "store_id": "jansen-1", "basestation_id": "bs-j2"})
    pos.put("/v1/stores/jansen-1/products/1", json={"name": "Worst", "price_cents": 199})
    pos.put("/v1/stores/jansen-1/labels/L1/product", json={"sku": "1"})
    hb(st1, "L1", rssi=-40)  # bs-j1 hoort het label beter, maar het is vast aan bs-j2
    assert st1.get("/v1/basestation/jobs").json() == []
    assert len(st2.get("/v1/basestation/jobs").json()) == 1
    label = pos.get("/v1/stores/jansen-1/labels/L1").json()
    assert label["pinned_basestation_id"] == "bs-j2" and label["basestation_id"] == "bs-j1"

    # Terug naar automatisch.
    r = m.put("/v1/manage/labels/L1/basestation", json={"basestation_id": None})
    assert r.json()["pinned_basestation_id"] is None


def test_sightings_and_self_registration(app, setup):
    m, pos, pos_b, st1, _st2, stb = setup
    m.post("/v1/manage/labels", json={"label_ids": ["STOCK1"], "display_type": "bwry_4_2"})
    pos_b.post("/v1/stores/buur-1/labels", json={"label_id": "BUUR1", "display_type": "bwry_2_9"})

    # Voorraadlabel claimen zonder dat het hier gehoord is: geweigerd.
    r = pos.post("/v1/stores/jansen-1/labels", json={"label_id": "STOCK1", "display_type": "bwr_2_13"})
    assert r.status_code == 403 and "managementsysteem" in r.json()["detail"]

    hb(st1, "STOCK1", "BUUR1", "NIEUW1")
    seen = {s["label_id"]: s for s in m.get("/v1/manage/stores/jansen-1/sightings").json()}
    assert seen["STOCK1"]["status"] == "stock" and seen["NIEUW1"]["status"] == "unknown"
    assert seen["BUUR1"]["status"] == "other_store" and seen["BUUR1"]["other_store"] == "buur-1"
    # Telemetrie van het buurlabel wordt niet overgenomen.
    assert pos_b.get("/v1/stores/buur-1/labels/BUUR1").json()["last_seen"] is None

    r = pos.post("/v1/stores/jansen-1/labels", json={"label_id": "STOCK1", "display_type": "bwr_2_13"})
    assert r.status_code == 201 and r.json()["display_type"] == "bwry_4_2"  # type uit de voorraad
    assert pos.post("/v1/stores/jansen-1/labels", json={"label_id": "BUUR1", "display_type": "bwry_2_9"}).status_code == 409
    assert "STOCK1" not in {s["label_id"] for s in m.get("/v1/manage/stores/jansen-1/sightings").json()}

    app.state.require_inventory = True
    r = pos.post("/v1/stores/jansen-1/labels", json={"label_id": "NIEUW1", "display_type": "bwry_2_9"})
    assert r.status_code == 403 and "voorraad" in r.json()["detail"]


def test_stock_labels_do_not_alert(setup, admin):
    m, *_rest = setup
    m.post("/v1/manage/labels", json={"label_ids": ["L1"], "display_type": "bwry_2_9"})
    assert [a for a in admin.get("/v1/monitoring/alerts").json() if a["subject_id"] == "L1"] == []


def test_basestation_stock_assign_move(setup):
    m, pos, *_ = setup
    bs = m.post("/v1/manage/basestations", json={"id": "bs-nieuw"}).json()
    assert bs["store_id"] is None
    station = TestClient(m.app if hasattr(m, "app") else pos.app, headers={"Authorization": f"Bearer {bs['token']}"})
    r = station.post("/v1/basestation/heartbeat", json={"software_version": "t", "uptime_s": 1})
    assert r.status_code == 409 and "voorraad" in r.json()["detail"]

    assert m.post("/v1/manage/basestations/bs-nieuw/assign", json={"store_id": "jansen-1"}).json()["store_id"] == "jansen-1"
    hb(station)
    m.post("/v1/manage/labels", json={"label_ids": ["L1"], "display_type": "bwry_2_9"})
    m.post("/v1/manage/labels/assign", json={"label_ids": ["L1"], "store_id": "jansen-1", "basestation_id": "bs-nieuw"})

    # Verplaatsen naar een andere klant: vaste koppelingen vervallen, licentie volgt de nieuwe winkel.
    m.post("/v1/manage/basestations/bs-nieuw/assign", json={"store_id": "buur-1"})
    assert pos.get("/v1/stores/jansen-1/labels/L1").json()["pinned_basestation_id"] is None
    hb(station)
    assert station.get("/v1/basestation/store").json()["id"] == "buur-1"

    m.post("/v1/manage/basestations/bs-nieuw/assign", json={"store_id": None})
    assert station.post("/v1/basestation/heartbeat", json={"software_version": "t", "uptime_s": 1}).status_code == 409
    statuses = {s["id"]: s for s in m.get("/v1/manage/basestations").json()}
    assert statuses["bs-nieuw"]["store_id"] is None and statuses["bs-nieuw"]["online"] is False


# --- beheer-webinterface ----------------------------------------------------------------------


@pytest.fixture
def ui(app, setup):
    with app.state.sessionmaker() as session:
        session.add(Operator(username="anna", password_hash=hash_password("anna-wachtwoord"), role="admin"))
        session.add(Operator(username="sam", password_hash=hash_password("sam-wachtwoord"), role="support"))
        session.commit()

    def login(user):
        c = TestClient(app)
        c.post("/beheer/login", data={"username": user, "password": f"{user}-wachtwoord"})
        return c
    return login


def test_beheer_stock_flow(setup, ui):
    _m, pos, _pb, st1, *_ = setup
    anna = ui("anna")
    r = anna.post("/beheer/voorraad/labels", data={"label_ids": "label_id,type\nc0:ff:ee:aa:00:01,bwry_2_9\nC0:FF:EE:AA:00:02",
                                                     "display_type": "bwry_2_9"})
    assert "2 label(s) op voorraad gezet" in r.text and "C0:FF:EE:AA:00:01" in r.text
    r = anna.post("/beheer/voorraad/labels/koppelen", data={"store_id": "jansen-1", "label_id": ["C0:FF:EE:AA:00:01"]})
    assert "1 label(s) gekoppeld aan Jansen" in r.text
    r = anna.post("/beheer/voorraad/basisstations", data={"bs_id": "bs-0042"})
    assert "Token voor basisstation bs-0042" in r.text

    # Winkelpagina: label vast aan basisstation, gehoorde labels koppelen, terug naar voorraad.
    r = anna.post("/beheer/winkels/jansen-1/labels/C0:FF:EE:AA:00:01/basisstation", data={"basestation_id": "bs-j1"})
    assert "vast via bs-j1" in r.text
    hb(st1, "C0:FF:EE:AA:00:02", "ONBEKEND9")
    page = anna.get("/beheer/winkels/jansen-1").text
    assert "Gehoord in deze winkel" in page and "ONBEKEND9" in page
    r = anna.post("/beheer/winkels/jansen-1/gehoord/ONBEKEND9", data={"display_type": "bw_1_54"})
    assert "Label ONBEKEND9 gekoppeld" in r.text
    assert pos.get("/v1/stores/jansen-1/labels/ONBEKEND9").json()["display_type"] == "bw_1_54"
    r = anna.post("/beheer/winkels/jansen-1/labels", data={"label_ids": "C0:FF:EE:AA:00:02", "basestation_id": "bs-j2"})
    assert "1 label(s) gekoppeld" in r.text
    r = anna.post("/beheer/winkels/jansen-1/labels/C0:FF:EE:AA:00:02/voorraad")
    assert "terug naar voorraad" in r.text
    r = anna.post("/beheer/basisstations/bs-j2/koppelen", data={"store_id": "voorraad", "back": "/beheer/winkels/jansen-1"})
    assert "bs-j2 terug naar voorraad" in r.text


def test_beheer_support_limits(setup, ui):
    _m, _pos, pos_b, st1, *_ = setup
    sam = ui("sam")
    pos_b.post("/v1/stores/buur-1/labels", json={"label_id": "BUUR1", "display_type": "bwry_2_9"})
    hb(st1, "BUUR1")
    r = sam.post("/beheer/winkels/jansen-1/gehoord/BUUR1", data={"move": "1"})
    assert "alleen een admin" in r.text
    assert sam.post("/beheer/basisstations/bs-j1/koppelen", data={"store_id": "buur-1"}).status_code == 403
    assert sam.get("/beheer/voorraad").status_code == 200
