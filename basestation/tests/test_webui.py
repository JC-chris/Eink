"""Webinterface basisstation, tegen een echte (in-memory) cloud."""

import re

import pytest
from fastapi.testclient import TestClient

from eink_basestation.agent import Agent
from eink_basestation.config import Config, hash_password
from eink_basestation.network import SimulatedNetwork
from eink_basestation.radio import SimulatedRadio
from eink_basestation.webui import create_webui, parse_euro
from eink_cloud.main import create_app

PASSWORD = "winkel-wachtwoord"
LABEL = "C0:FF:EE:00:00:09"


@pytest.fixture
def env(tmp_path):
    cloud_app = create_app("sqlite://", "adm", monitor_interval_s=None)
    admin = TestClient(cloud_app, headers={"Authorization": "Bearer adm"})
    store = admin.post("/v1/admin/stores", json={"id": "bakkerij", "name": "Bakkerij De Vries"}).json()
    bs = admin.post("/v1/admin/stores/bakkerij/basestations", json={"id": "bs-1"}).json()

    config = Config(server="http://testserver", token=bs["token"], password_hash=hash_password(PASSWORD))
    factory = lambda c: TestClient(cloud_app, headers={"Authorization": f"Bearer {c.token}"})  # noqa: E731
    radio = SimulatedRadio()
    radio.add_label(LABEL)
    agent = Agent(factory(config), radio)
    config.ensure_hotspot()
    ui = TestClient(create_webui(config, tmp_path / "config.json", agent, factory, SimulatedNetwork()))
    pos = TestClient(cloud_app, headers={"Authorization": f"Bearer {store['api_key']}"})
    return ui, agent, pos, config, tmp_path


def login(ui, password=PASSWORD):
    return ui.post("/login", data={"password": password}, follow_redirects=False)


def test_parse_euro():
    assert parse_euro("12,95") == 1295
    assert parse_euro("€ 3.5") == 350
    assert parse_euro("1.234,50") == 123450
    assert parse_euro(" ") is None
    for bad in ("abc", "-1", "1,234"):
        with pytest.raises(ValueError):
            parse_euro(bad)


def test_login_required(env):
    ui, *_ = env
    for path in ("/", "/producten", "/labels", "/instellingen"):
        r = ui.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
    assert "Onjuist wachtwoord" in login(ui, "fout").text
    r = login(ui)
    assert r.status_code == 303 and "eink_session" in r.cookies
    assert "Bakkerij De Vries" in ui.get("/").text


def test_csrf_foreign_origin_rejected(env):
    ui, *_ = env
    login(ui)
    r = ui.post("/instellingen/prijsbron", data={"price_source": "manual"},
                headers={"origin": "http://evil.example"}, follow_redirects=False)
    assert r.headers["location"] == "/login"


def test_manual_price_management_without_pos(env):
    ui, agent, pos, *_ = env
    login(ui)

    # Standaard: kassa is de bron, webinterface mag geen prijzen wijzigen.
    page = ui.get("/producten").text
    assert "Prijzen komen uit de kassa" in page and "Product toevoegen" not in page
    r = ui.post("/producten", data={"sku": "10", "name": "Desem", "price": "4,45"})
    assert "worden beheerd via de kassa" in r.text

    # Omschakelen naar de webinterface.
    r = ui.post("/instellingen/prijsbron", data={"price_source": "manual"})
    assert "Prijzen worden nu beheerd via deze webinterface" in r.text
    r = ui.post("/producten", data={"sku": "10", "name": "Desembrood", "price": "4,45", "unit": "st", "origin": "Eigen bakkerij"})
    assert "Desembrood opgeslagen" in r.text and "€ 4,45" in r.text

    # Kassa wordt nu geweigerd, zodat ze elkaar niet overschrijven.
    r = pos.put("/v1/stores/bakkerij/products/10", json={"name": "x", "price_cents": 1})
    assert r.status_code == 409 and "webinterface" in r.json()["detail"]

    # Nieuw label in bereik registreren en koppelen.
    agent.heartbeat()
    page = ui.get("/labels").text
    assert "Nieuwe labels in bereik" in page and LABEL in page
    r = ui.post("/labels/registreren", data={"label_id": LABEL, "display_type": "bwry_2_9"})
    assert f"Label {LABEL} geregistreerd" in r.text and "Nieuwe labels in bereik" not in r.text
    r = ui.post(f"/labels/{LABEL}/koppelen", data={"sku": "10"})
    assert "gekoppeld aan 10" in r.text and "Wordt bijgewerkt" in r.text

    # Basisstation verstuurt het beeld; label is daarna actueel.
    assert agent.process_jobs() == 1
    assert "Actueel" in ui.get("/labels").text
    png = ui.get(f"/labels/{LABEL}/preview.png")
    assert png.content[:4] == b"\x89PNG"

    # Prijswijziging via webinterface gaat direct naar het label.
    r = ui.post("/producten", data={"sku": "10", "name": "Desembrood", "price": "4,65", "unit": "st"})
    assert "1 label(s) worden bijgewerkt" in r.text
    assert agent.process_jobs() == 1

    # Terug naar kassa: webinterface weer alleen-lezen, kassa werkt weer.
    ui.post("/instellingen/prijsbron", data={"price_source": "pos"})
    assert pos.put("/v1/stores/bakkerij/products/10", json={"name": "Desembrood", "price_cents": 475}).status_code == 200
    assert "€ 4,75" in ui.get("/producten").text


def test_invalid_price_shows_error(env):
    ui, *_ = env
    login(ui)
    ui.post("/instellingen/prijsbron", data={"price_source": "manual"})
    r = ui.post("/producten", data={"sku": "1", "name": "Brood", "price": "twee euro"})
    assert "ongeldige prijs" in r.text


def test_change_password_and_cloud_settings(env):
    ui, agent, _pos, config, tmp_path = env
    login(ui)
    r = ui.post("/instellingen/wachtwoord", data={"current": "fout", "new": "nieuwwachtwoord", "repeat": "nieuwwachtwoord"})
    assert "Huidig wachtwoord onjuist" in r.text
    r = ui.post("/instellingen/wachtwoord", data={"current": PASSWORD, "new": "kort", "repeat": "kort"})
    assert "minimaal 8" in r.text
    r = ui.post("/instellingen/wachtwoord", data={"current": PASSWORD, "new": "nieuwwachtwoord", "repeat": "nieuwwachtwoord"})
    assert "Wachtwoord gewijzigd" in r.text
    assert Config.load(tmp_path / "config.json").password_hash == config.password_hash

    # Leeg token = bestaande behouden.
    old_token = config.token
    r = ui.post("/instellingen/cloud", data={"server": "http://testserver/", "token": ""})
    assert "Cloudverbinding opgeslagen" in r.text
    assert config.token == old_token and config.server == "http://testserver"
    assert re.search(r"ingesteld — leeg laten", r.text)

    ui.cookies.clear()
    assert login(ui, PASSWORD).status_code == 200  # oud wachtwoord werkt niet meer (formulier opnieuw)
    assert login(ui, "nieuwwachtwoord").status_code == 303


def test_unconfigured_station(tmp_path):
    config = Config(token="")
    assert config.ensure_password() is not None and config.ensure_password() is None
    agent = Agent(None, SimulatedRadio())
    assert agent.run_once() == 0 and "niet geconfigureerd" in agent.status.last_error
    config.password_hash = hash_password(PASSWORD)
    ui = TestClient(create_webui(config, tmp_path / "c.json", agent, lambda c: None))
    login(ui)
    assert "nog niet met de cloud verbonden" in ui.get("/").text


def test_network_page(env):
    ui, _agent, _pos, config, tmp_path = env
    login(ui)
    page = ui.get("/netwerk").text
    assert "192.168.1.23/24" in page and "Winkel-WiFi" in page and config.hotspot_ssid in page
    assert "Ethernet" in ui.get("/").text

    r = ui.post("/netwerk/ethernet", data={"method": "static", "address": "192.168.1.50/24", "gateway": "10.0.0.1"})
    assert "ligt niet in het netwerk" in r.text
    r = ui.post("/netwerk/ethernet", data={"method": "static", "address": "192.168.1.50/24",
                                           "gateway": "192.168.1.1", "dns": "1.1.1.1, 8.8.8.8"})
    assert "vast IP-adres 192.168.1.50" in r.text and 'value="1.1.1.1 8.8.8.8"' in r.text
    r = ui.post("/netwerk/ethernet", data={"method": "dhcp"})
    assert "Ethernet ingesteld op DHCP" in r.text

    r = ui.post("/netwerk/wifi", data={"ssid": "Winkel-WiFi", "password": "fout-wachtwoord"})
    assert "onjuist wachtwoord" in r.text
    r = ui.post("/netwerk/wifi", data={"ssid": "Winkel-WiFi", "password": "geheim123"})
    assert "Verbonden met Wi-Fi Winkel-WiFi" in r.text and "Vergeten" in r.text
    r = ui.post("/netwerk/wifi/vergeten")
    assert "Wi-Fi-netwerk vergeten" in r.text

    r = ui.post("/netwerk/hotspot", data={})
    assert "hotspot staat uit" in r.text
    assert Config.load(tmp_path / "config.json").hotspot_enabled is False


def test_design_page_and_product_design_fields(env):
    ui, _agent, pos, *_ = env
    login(ui)
    page = ui.get("/ontwerp").text
    assert "Labelontwerp" in page and "Ambachtelijk" in page and "/ontwerp/vis/voorbeeld.png" in page
    assert ui.get("/ontwerp/vis/voorbeeld.png?display_type=bwry_4_2").content[:4] == b"\x89PNG"
    r = ui.post("/ontwerp", data={"template": "bakker"})
    assert "Ontwerp opgeslagen" in r.text
    assert pos.get("/v1/stores/bakkerij").json()["label_template"] == "bakker"

    ui.post("/instellingen/prijsbron", data={"price_source": "manual"})
    assert "Winkelontwerp (bakker)" in ui.get("/producten").text
    r = ui.post("/producten", data={"sku": "5", "name": "Appeltaart", "price": "12,50", "was_price": "14,95",
                                    "description": "Met kaneel en rozijnen", "template": "actie", "promo_text": "Actie"})
    assert "Appeltaart opgeslagen" in r.text and "(van € 14,95)" in r.text
    p = pos.get("/v1/stores/bakkerij/products/5").json()
    assert (p["was_price_cents"], p["description"], p["template"]) == (1495, "Met kaneel en rozijnen", "actie")


def test_standard_assortment(env):
    ui, _agent, pos, *_ = env
    login(ui)
    ui.post("/instellingen/prijsbron", data={"price_source": "manual"})
    page = ui.get("/producten").text
    assert "kies uit het standaard assortiment" in page and 'list="suggesties"' in page and "Kabeljauwfilet" in page

    page = ui.get("/producten/assortiment").text
    assert "Slagerij" in page and "Bakkerij" in page
    page = ui.get("/producten/assortiment?branche=bakkerij").text
    assert "Volkorenbrood" in page and "BA001" in page and "winkelontwerp op <strong>bakker</strong>" in page

    # Prijs ontbreekt bij een aangevinkt product → foutmelding, ingevulde waarden blijven staan.
    r = ui.post("/producten/assortiment", data={"branche": "bakkerij", "pick": ["0", "2"], "price_0": "3,45", "price_2": ""})
    assert "Witbrood: prijs ontbreekt" in r.text and 'value="3,45"' in r.text

    r = ui.post("/producten/assortiment", data={"branche": "bakkerij", "pick": ["0", "2"], "price_0": "3,45",
                                                "price_2": "2,10", "sku_2": "77", "set_template": "1"})
    assert "2 producten toegevoegd uit het assortiment Bakkerij" in r.text
    assert pos.get("/v1/stores/bakkerij/products/BA001").json()["price_cents"] == 345
    assert pos.get("/v1/stores/bakkerij/products/77").json()["name"] == "Witbrood"
    assert pos.get("/v1/stores/bakkerij").json()["label_template"] == "bakker"
    # Daarna gemarkeerd als al aanwezig.
    assert "al aanwezig · € 3,45" in ui.get("/producten/assortiment?branche=bakkerij").text


def test_fish_species_choice_and_sauces(env):
    ui, _agent, pos, *_ = env
    login(ui)
    ui.post("/instellingen/prijsbron", data={"price_source": "manual"})
    page = ui.get("/producten/assortiment?branche=vis").text
    assert "— kies de vissoort —" in page and "Pollak (Pollachius pollachius)" in page and "Knoflook, Ravigotte" in page
    # Kibbeling (index 0) zonder vissoort → fout.
    r = ui.post("/producten/assortiment", data={"branche": "vis", "pick": ["0"], "price_0": "6,50"})
    assert "Kibbeling: kies de vissoort" in r.text
    r = ui.post("/producten/assortiment", data={"branche": "vis", "pick": ["0"], "price_0": "6,50",
                                                "variant_0": "Pollak (Pollachius pollachius)", "opt_0": "Knoflook, Cocktail"})
    assert "1 producten toegevoegd" in r.text
    p = pos.get("/v1/stores/bakkerij/products/VI001").json()
    assert p["description"] == "Pollak (Pollachius pollachius)" and p["options"] == ["Knoflook", "Cocktail"]

    r = ui.post("/producten", data={"sku": "9", "name": "Visburger", "price": "4,50", "options": "chili, knoflook",
                                    "options_label": "Saus"})
    assert "Visburger opgeslagen" in r.text
    assert pos.get("/v1/stores/bakkerij/products/9").json()["options_label"] == "Saus"
