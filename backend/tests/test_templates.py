"""Labelontwerpen: elk ontwerp op elk display, winkel-standaard en per-product-keuze."""

import base64

import pytest
from fastapi.testclient import TestClient

from eink_cloud.displays import DISPLAY_TYPES
from eink_cloud.label_templates import TEMPLATES
from eink_cloud.models import Operator
from eink_cloud.render import LabelContent, render_frame
from eink_cloud.security import hash_password

LONG = "Heel erg lange productnaam die nooit op een klein label past " * 3
CONTENTS = [
    LabelContent("Biefstuk", 2995, "kg"),
    LabelContent(LONG, 123456, "100g", unit_price_cents=99999, origin=LONG, promo_text=LONG, was_price_cents=999999,
                 description=LONG * 3),
    LabelContent("X", 0, "st", was_price_cents=100, promo_text="Actie"),
]


@pytest.mark.parametrize("template", TEMPLATES)
@pytest.mark.parametrize("display", DISPLAY_TYPES.values(), ids=lambda d: d.id)
def test_every_template_on_every_display(template, display):
    for c in CONTENTS:
        c.template = template
        frame, img = render_frame(c, display)
        assert img.size == (display.width, display.height)
        assert max(img.tobytes()) < len(display.palette)
        assert render_frame(c, display)[0].crc32 == frame.crc32  # deterministisch


def test_templates_differ():
    d = DISPLAY_TYPES["bwry_2_9"]
    crcs = {t: render_frame(LabelContent("Biefstuk", 2995, "kg", template=t, origin="NL", description="Mals"), d)[0].crc32
            for t in TEMPLATES}
    assert len(set(crcs.values())) == len(TEMPLATES)


def test_store_template_and_product_override(store):
    pos, station = store
    for lid, sku in (("C0:FF:EE:00:00:01", "1"), ("C0:FF:EE:00:00:02", "2")):
        pos.post("/v1/stores/slagerij-jansen/labels", json={"label_id": lid, "display_type": "bwry_2_9"})
        pos.put(f"/v1/stores/slagerij-jansen/labels/{lid}/product", json={"sku": sku})
    pos.put("/v1/stores/slagerij-jansen/products/1", json={"name": "Biefstuk", "price_cents": 2995, "unit": "kg"})
    pos.put("/v1/stores/slagerij-jansen/products/2", json={"name": "Kipfilet", "price_cents": 899, "unit": "kg",
                                                           "template": "actie", "was_price_cents": 1199,
                                                           "promo_text": "Weekaanbieding"})
    assert pos.get("/v1/stores/slagerij-jansen/products/2").json()["template"] == "actie"
    for job in station.get("/v1/basestation/jobs").json():
        station.post(f"/v1/basestation/jobs/{job['job_id']}/result", json={"success": True, "displayed_crc": job["crc32"]})

    r = station.put("/v1/basestation/store/settings", json={"label_template": "ambachtelijk"})
    assert r.json()["label_template"] == "ambachtelijk"
    jobs = station.get("/v1/basestation/jobs").json()
    assert [j["label_id"] for j in jobs] == ["C0:FF:EE:00:00:01"]  # product 2 houdt zijn eigen ontwerp

    assert station.put("/v1/basestation/store/settings", json={"label_template": "bestaat-niet"}).status_code == 422
    assert pos.put("/v1/stores/slagerij-jansen/products/3", json={"name": "x", "price_cents": 1,
                                                                  "template": "fout"}).status_code == 422
    assert {t["id"] for t in pos.get("/v1/stores/slagerij-jansen/templates").json()} == set(TEMPLATES)


def test_template_previews(store):
    pos, station = store
    for t in TEMPLATES:
        r = station.get(f"/v1/basestation/store/templates/{t}/preview.png", params={"display_type": "bwry_4_2", "promo": True})
        assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert station.get("/v1/basestation/store/templates/nope/preview.png").status_code == 404
    pos.put("/v1/stores/slagerij-jansen/products/1", json={"name": "Biefstuk", "price_cents": 2995})
    assert station.get("/v1/basestation/store/templates/vis/preview.png", params={"sku": "1"}).status_code == 200


def test_import_with_design_columns(store):
    pos, _ = store
    csv = "PLU;Omschrijving;Prijs;Van prijs;Toelichting;Ontwerp\n1;Kabeljauw;24,95;29,95;Gadus morhua;Vis\n"
    d = pos.post("/v1/stores/slagerij-jansen/products:import",
                 json={"filename": "x.csv", "content_b64": base64.b64encode(csv.encode()).decode(), "dry_run": False}).json()
    assert d["imported"] == 1, d
    p = pos.get("/v1/stores/slagerij-jansen/products/1").json()
    assert (p["was_price_cents"], p["description"], p["template"]) == (2995, "Gadus morhua", "vis")


def test_beheer_design(app, store):
    with app.state.sessionmaker() as session:
        session.add(Operator(username="sam", password_hash=hash_password("sam-wachtwoord"), role="support"))
        session.commit()
    ui = TestClient(app)
    ui.post("/beheer/login", data={"username": "sam", "password": "sam-wachtwoord"})
    page = ui.get("/beheer/winkels/slagerij-jansen").text
    assert "Labelontwerp" in page and "/ontwerp/bakker.png" in page
    assert ui.get("/beheer/winkels/slagerij-jansen/ontwerp/bakker.png").content[:4] == b"\x89PNG"
    r = ui.post("/beheer/winkels/slagerij-jansen/ontwerp", data={"template": "bakker"})
    assert "Ontwerp &#39;Bakker&#39; ingesteld" in r.text or "Ontwerp 'Bakker' ingesteld" in r.text
    assert "onbekend ontwerp" in ui.post("/beheer/winkels/slagerij-jansen/ontwerp", data={"template": "x"}).text
