"""Prijslijsten inlezen (CSV/Excel) en importeren."""

import base64
import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from eink_cloud.models import Operator
from eink_cloud.pricefile import (
    PriceFileError, build_items, guess_mapping, parse_price, parse_unit, read_table,
)
from eink_cloud.security import hash_password

SLAGER_CSV = "PLU;Omschrijving;Prijs;Eenheid;Herkomst;Actie\n1001;Runderbiefstuk;€ 29,95;kg;Nederland;Weekaanbieding\n2001;Slavink;1,85;st;;\n;;;;;\n"


def xlsx(rows) -> bytes:
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def b64(data) -> str:
    return base64.b64encode(data if isinstance(data, bytes) else data.encode()).decode()


@pytest.mark.parametrize("text, cents", [("29,95", 2995), ("€ 1.234,50", 123450), ("12.5", 1250), ("1,234.56", 123456),
                                          ("7", 700), (" 0,99 ", 99)])
def test_parse_price(text, cents):
    assert parse_price(text) == cents


@pytest.mark.parametrize("text", ["", "abc", "-1"])
def test_parse_price_invalid(text):
    with pytest.raises(ValueError):
        parse_price(text)


def test_parse_unit():
    assert [parse_unit(u) for u in ("KG", "per kg", "Stuk", "100 gr", "ja", "nee")] == ["kg", "kg", "st", "100g", "kg", "st"]
    with pytest.raises(ValueError, match="onbekende eenheid"):
        parse_unit("doos")


def test_read_csv_cp1252_semicolon():
    t = read_table(SLAGER_CSV.replace("Runderbiefstuk", "Paté").encode("cp1252"), "export.csv")
    assert t.columns == ["PLU", "Omschrijving", "Prijs", "Eenheid", "Herkomst", "Actie"]
    assert t.rows[0][1] == "Paté" and len(t.rows) == 2  # lege regel valt weg


def test_read_csv_comma_and_tab():
    t = read_table(b'artikelnummer,naam,verkoopprijs\n1,"Brood, wit","1,85"\n', "x.csv")
    assert t.rows == [["1", "Brood, wit", "1,85"]]
    t = read_table(b"code\tdescription\tprice\n7\tRoll\t0.45\n", "x.txt")
    assert guess_mapping(t.columns) == {"sku": "code", "name": "description", "price": "price"}


def test_read_xlsx_numbers():
    t = read_table(xlsx([["PLU", "Naam", "Prijs"], [1001, "Biefstuk", 29.95], [2001.0, "Worst", 3]]), "lijst.xlsx")
    assert t.rows == [["1001", "Biefstuk", "29.95"], ["2001", "Worst", "3"]]


def test_read_errors():
    with pytest.raises(PriceFileError, match="leeg"):
        read_table(b"\n\n", "x.csv")
    with pytest.raises(PriceFileError, match=".xls"):
        read_table(b"\xd0\xcf\x11\xe0", "oud.xls")
    with pytest.raises(PriceFileError, match="Excel"):
        read_table(b"PK\x03\x04kapot", "kapot.xlsx")


def test_build_items_and_errors():
    t = read_table(SLAGER_CSV.encode(), "x.csv")
    m = guess_mapping(t.columns)
    assert m == {"sku": "PLU", "name": "Omschrijving", "price": "Prijs", "unit": "Eenheid", "origin": "Herkomst",
                 "promo_text": "Actie"}
    r = build_items(t, m)
    assert [(i.sku, i.price_cents, i.unit, i.promo_text) for i in r.items] == [
        ("1001", 2995, "kg", "Weekaanbieding"), ("2001", 185, "st", None)]
    assert r.skipped == 0 and r.errors == []

    bad = read_table(b"PLU;Naam;Prijs\n1;A;1,00\n1;B;2,00\n2;;3,00\n3;C;gratis\n;D;1\n", "x.csv")
    r = build_items(bad, guess_mapping(bad.columns))
    assert [i.sku for i in r.items] == ["1"]
    assert [e["row"] for e in r.errors] == [3, 4, 5, 6]
    assert "dubbel" in r.errors[0]["message"] and "naam" in r.errors[1]["message"]

    r = build_items(t, {"sku": "PLU"})
    assert r.items == [] and "Naam" in r.errors[0]["message"]
    with pytest.raises(PriceFileError, match="niet in het bestand"):
        build_items(t, {"sku": "Bestaat niet", "name": "Omschrijving", "price": "Prijs"})


# --- API ---------------------------------------------------------------------------------------


def test_pos_import_dry_run_then_import(store):
    pos, _station = store
    pos.post("/v1/stores/slagerij-jansen/labels", json={"label_id": "C0:FF:EE:00:00:01", "display_type": "bwry_2_9"})
    pos.put("/v1/stores/slagerij-jansen/labels/C0:FF:EE:00:00:01/product", json={"sku": "1001"})

    r = pos.post("/v1/stores/slagerij-jansen/products:import", json={"filename": "export.csv", "content_b64": b64(SLAGER_CSV)})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["dry_run"] and d["valid"] == 2 and d["imported"] == 0 and d["preview"][0]["name"] == "Runderbiefstuk"
    assert pos.get("/v1/stores/slagerij-jansen/products").json() == []

    d = pos.post("/v1/stores/slagerij-jansen/products:import",
                 json={"filename": "export.csv", "content_b64": b64(SLAGER_CSV), "dry_run": False}).json()
    assert d["imported"] == 2 and d["labels_scheduled"] == 1
    assert pos.get("/v1/stores/slagerij-jansen/products/1001").json()["price_cents"] == 2995

    # Volgende export met andere kolomvolgorde en zonder mapping: bewaarde indeling wordt gebruikt.
    nxt = "Actie;Prijs;Omschrijving;PLU;Eenheid;Herkomst\n;31,50;Runderbiefstuk;1001;kg;Ierland\n"
    d = pos.post("/v1/stores/slagerij-jansen/products:import",
                 json={"filename": "export2.csv", "content_b64": b64(nxt), "dry_run": False}).json()
    assert d["imported"] == 1
    assert pos.get("/v1/stores/slagerij-jansen/products/1001").json()["origin"] == "Ierland"


def test_import_all_or_nothing_and_validation(store):
    pos, _ = store
    bad = "PLU;Naam;Prijs\n1;Brood;2,00\n2;Kaas;duur\n"
    d = pos.post("/v1/stores/slagerij-jansen/products:import",
                 json={"filename": "x.csv", "content_b64": b64(bad), "dry_run": False}).json()
    assert d["imported"] == 0 and d["errors"][0]["row"] == 3
    assert pos.get("/v1/stores/slagerij-jansen/products").json() == []
    r = pos.post("/v1/stores/slagerij-jansen/products:import", json={"filename": "x.csv", "content_b64": "!!geen base64"})
    assert r.status_code == 422
    r = pos.post("/v1/stores/slagerij-jansen/products:import", json={"filename": "x.xls", "content_b64": b64(b"\xd0\xcf")})
    assert r.status_code == 422 and ".xlsx" in r.json()["detail"]


def test_import_respects_price_source(store, admin):
    pos, station = store
    body = {"filename": "x.csv", "content_b64": b64(SLAGER_CSV), "dry_run": False}
    assert station.post("/v1/basestation/store/products:import?source=upload", json=body).status_code == 409
    assert station.post("/v1/basestation/store/products:import?source=folder", json=body).json()["imported"] == 2
    station.put("/v1/basestation/store/settings", json={"price_source": "manual"})
    assert pos.post("/v1/stores/slagerij-jansen/products:import", json=body).status_code == 409
    assert station.post("/v1/basestation/store/products:import?source=folder", json=body).status_code == 409
    assert station.post("/v1/basestation/store/products:import?source=upload", json=body).json()["imported"] == 2
    assert station.post("/v1/basestation/store/products:import?source=x", json=body).status_code == 422


def test_beheer_import_page(app, store):
    with app.state.sessionmaker() as session:
        session.add(Operator(username="sam", password_hash=hash_password("sam-wachtwoord"), role="support"))
        session.commit()
    ui = TestClient(app)
    ui.post("/beheer/login", data={"username": "sam", "password": "sam-wachtwoord"})
    assert "Prijslijst importeren" in ui.get("/beheer/winkels/slagerij-jansen").text
    data = xlsx([["Artikel", "Benaming", "VK prijs"], [5, "Kipfilet", 12.49]])
    r = ui.post("/beheer/winkels/slagerij-jansen/import", files={"file": ("lijst.xlsx", data)})
    # "Artikel" wordt als naam herkend; er is geen artikelnummerkolom → het systeem vraagt erom.
    assert "lijst.xlsx" in r.text and "kies een kolom voor: Artikelnummer" in r.text
    assert 'name="content_b64"' in r.text and "Los eerst de fouten op" in r.text
    # Zelf de juiste kolommen kiezen, dan importeren.
    form = {"content_b64": b64(data), "filename": "lijst.xlsx", "mapped": "1", "map_sku": "Artikel",
            "map_name": "Benaming", "map_price": "VK prijs", "default_unit": "kg", "action": "import"}
    r = ui.post("/beheer/winkels/slagerij-jansen/import", data=form)
    assert "1 producten geïmporteerd uit lijst.xlsx" in r.text
    pos, _ = store
    p = pos.get("/v1/stores/slagerij-jansen/products/5").json()
    assert p["unit"] == "kg" and p["price_cents"] == 1249
