"""Standaard assortimenten per branche."""

from eink_cloud.assortments import ASSORTMENTS, suggestions
from eink_cloud.label_templates import TEMPLATES
from eink_cloud.schemas import ProductBatchItem


def test_assortments_are_valid():
    for a in ASSORTMENTS.values():
        assert a.template in TEMPLATES and len(a.items) >= 15
        d = a.as_dict()
        skus = [i["sku"] for i in d["items"]]
        names = [i["name"] for i in d["items"]]
        assert len(set(skus)) == len(skus) and len(set(names)) == len(names)
        for item in d["items"]:
            ProductBatchItem(sku=item["sku"], name=item["name"], price_cents=100, unit=item["unit"],
                             description=item["description"], template=item["template"])


def test_fish_has_scientific_names():
    fresh = [i for i in ASSORTMENTS["vis"].items if i.name in ("Kabeljauwfilet", "Zalmfilet", "Scholfilet")]
    assert all(i.description and " " in i.description for i in fresh)


def test_suggestions_unique_and_fish_template():
    s = suggestions()
    names = [x["name"] for x in s]
    assert len(names) == len(set(names)) and "Runderbiefstuk" in names
    assert next(x for x in s if x["name"] == "Kabeljauwfilet")["template"] == "vis"


def test_api(store):
    pos, station = store
    assert {a["id"] for a in station.get("/v1/basestation/assortments").json()} == set(ASSORTMENTS)
    assert station.get("/v1/basestation/assortments/vis").json()["items"][0]["sku"] == "VI001"
    assert station.get("/v1/basestation/assortments/nope").status_code == 404
    assert len(station.get("/v1/basestation/product-suggestions").json()) > 100
    assert len(pos.get("/v1/stores/slagerij-jansen/assortments").json()) == len(ASSORTMENTS)

    batch = [{"sku": "SL001", "name": "Runderbiefstuk", "price_cents": 2995, "unit": "kg"}]
    assert station.post("/v1/basestation/store/products:batch", json=batch).status_code == 409  # prijsbron kassa
    station.put("/v1/basestation/store/settings", json={"price_source": "manual"})
    assert station.post("/v1/basestation/store/products:batch", json=batch).json()[0]["sku"] == "SL001"
