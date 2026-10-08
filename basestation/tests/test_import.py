"""Prijslijst importeren via de webinterface en de importmap van het basisstation."""

import base64

import pytest
from fastapi.testclient import TestClient

from eink_basestation.agent import Agent
from eink_basestation.config import Config, hash_password
from eink_basestation.folder_import import FolderImporter
from eink_basestation.radio import SimulatedRadio
from eink_basestation.webui import create_webui
from eink_cloud.main import create_app

CSV = "PLU;Omschrijving;Prijs;Eenheid\n1001;Runderbiefstuk;29,95;kg\n2001;Slavink;1,85;st\n"


@pytest.fixture
def env(tmp_path):
    cloud = create_app("sqlite://", "adm", monitor_interval_s=None)
    admin = TestClient(cloud, headers={"Authorization": "Bearer adm"})
    store = admin.post("/v1/admin/stores", json={"id": "winkel", "name": "Winkel", "price_source": "manual"}).json()
    bs = admin.post("/v1/admin/stores/winkel/basestations", json={"id": "bs-1"}).json()
    config = Config(server="http://testserver", token=bs["token"], password_hash=hash_password("wachtwoord1"),
                    import_dir=str(tmp_path / "import"))
    factory = lambda c: TestClient(cloud, headers={"Authorization": f"Bearer {c.token}"})  # noqa: E731
    pos = TestClient(cloud, headers={"Authorization": f"Bearer {store['api_key']}"})
    return config, factory, pos, tmp_path


def test_webui_upload(env):
    config, factory, pos, tmp_path = env
    ui = TestClient(create_webui(config, tmp_path / "c.json", Agent(factory(config), SimulatedRadio()), factory))
    ui.post("/login", data={"password": "wachtwoord1"})
    assert "importeer een Excel/CSV-prijslijst" in ui.get("/producten").text
    r = ui.post("/producten/import", files={"file": ("prijzen.csv", CSV.encode())})
    assert "2</strong> goede regels" in r.text and "Runderbiefstuk" in r.text
    r = ui.post("/producten/import", data={"content_b64": base64.b64encode(CSV.encode()).decode(), "filename": "prijzen.csv",
                                           "mapped": "1", "map_sku": "PLU", "map_name": "Omschrijving",
                                           "map_price": "Prijs", "map_unit": "Eenheid", "action": "import"})
    assert "2 producten geïmporteerd" in r.text and "€ 29,95" in r.text

    # Bij prijsbron kassa wordt uploaden geweigerd, met uitleg.
    ui.post("/instellingen/prijsbron", data={"price_source": "pos"})
    r = ui.post("/producten/import", files={"file": ("prijzen.csv", CSV.encode())})
    assert "webinterface van het basisstation" not in r.text and "worden beheerd via de kassa" in r.text


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def test_folder_import(env):
    config, factory, pos, tmp_path = env
    pos_cloud = factory(config)
    pos_cloud.put("/v1/basestation/store/settings", json={"price_source": "pos"})
    clock = Clock()
    imp = FolderImporter(config, factory, clock=clock)
    assert imp.tick() == 0  # uit

    config.import_enabled = True
    imp.ensure_dirs()
    folder = tmp_path / "import"
    (folder / "export.csv").write_text(CSV, encoding="utf-8")
    (folder / "notities.pdf").write_bytes(b"%PDF")
    assert imp.tick() == 0  # eerst zien dat het bestand niet meer groeit
    clock.t += 6
    assert imp.tick() == 1
    assert not (folder / "export.csv").exists() and (folder / "notities.pdf").exists()
    done = list((folder / "verwerkt").iterdir())
    assert any(p.name.endswith("_export.csv") for p in done)
    assert "2 producten bijgewerkt" in next(p for p in done if p.name.endswith(".resultaat.txt")).read_text()
    assert imp.last.ok and pos.get("/v1/stores/winkel/products/1001").json()["price_cents"] == 2995

    (folder / "fout.csv").write_text("PLU;Omschrijving;Prijs\n1;Brood;gratis\n", encoding="utf-8")
    imp.tick()
    clock.t += 6
    imp.tick()
    failed = list((folder / "fout").iterdir())
    assert any("regel 2" in p.read_text() for p in failed if p.name.endswith(".resultaat.txt"))
    assert not imp.last.ok


def test_folder_import_waits_when_cloud_unreachable(env):
    import httpx

    config, _factory, _pos, tmp_path = env
    config.import_enabled = True
    clock = Clock()
    dead = lambda c: httpx.Client(base_url="http://127.0.0.1:9", timeout=0.2)  # noqa: E731
    imp = FolderImporter(config, dead, clock=clock)
    imp.ensure_dirs()
    (tmp_path / "import" / "export.csv").write_text(CSV, encoding="utf-8")
    imp.tick()
    clock.t += 6
    assert imp.tick() == 0
    assert (tmp_path / "import" / "export.csv").exists()  # blijft staan voor een volgende poging
