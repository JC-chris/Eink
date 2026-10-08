"""Keuzes op het label (sauzen) en vissoort-keuze bij kibbeling/lekkerbekje."""

import base64

import pytest

from eink_cloud.assortments import ASSORTMENTS, WHITEFISH
from eink_cloud.displays import DISPLAY_TYPES
from eink_cloud.render import LabelContent, options_text, render_frame
from eink_cloud.schemas import ProductIn


def test_options_parsing_and_text():
    assert ProductIn(name="x", price_cents=1, options="knoflook; ravigotte| cocktail ,").options == [
        "knoflook", "ravigotte", "cocktail"]
    assert ProductIn(name="x", price_cents=1, options="").options is None
    with pytest.raises(ValueError):
        ProductIn(name="x", price_cents=1, options=["x" * 31])
    c = LabelContent("Kibbeling", 650, options=("Knoflook", "Cocktail"))
    assert options_text(c) == "Saus naar keuze: Knoflook, Cocktail"
    c.options_label = "Dip"
    assert options_text(c) == "Dip: Knoflook, Cocktail"


def test_options_change_the_label():
    d = DISPLAY_TYPES["bwry_2_9"]
    for template in ("standaard", "vis", "markt", "krijtbord"):  # krijtbord: achter de omschrijving
        base = LabelContent("Kibbeling", 650, description="Pollak (Pollachius pollachius)", template=template)
        with_opts = LabelContent("Kibbeling", 650, description="Pollak (Pollachius pollachius)", template=template,
                                 options=("Knoflook", "Cocktail"))
        assert render_frame(base, d)[0].crc32 != render_frame(with_opts, d)[0].crc32, template


def test_kibbeling_has_no_default_species():
    vis = {i.name: i for i in ASSORTMENTS["vis"].items}
    for name in ("Kibbeling", "Lekkerbekje"):
        assert vis[name].description is None and vis[name].variants == WHITEFISH
        assert "Knoflook" in vis[name].options
    assert any("Pollachius pollachius" in v for v in WHITEFISH)


def test_options_via_api_and_import(store):
    pos, _ = store
    pos.put("/v1/stores/slagerij-jansen/products/1", json={"name": "Kibbeling", "price_cents": 650,
                                                           "description": "Pollak (Pollachius pollachius)",
                                                           "options": ["Knoflook", "Ravigotte"]})
    p = pos.get("/v1/stores/slagerij-jansen/products/1").json()
    assert p["options"] == ["Knoflook", "Ravigotte"] and p["options_label"] is None
    csv = "PLU;Omschrijving;Prijs;Sauzen\n2;Lekkerbekje;5,95;knoflook, cocktail\n"
    d = pos.post("/v1/stores/slagerij-jansen/products:import",
                 json={"filename": "x.csv", "content_b64": base64.b64encode(csv.encode()).decode(), "dry_run": False}).json()
    assert d["imported"] == 1
    assert pos.get("/v1/stores/slagerij-jansen/products/2").json()["options"] == ["knoflook", "cocktail"]
