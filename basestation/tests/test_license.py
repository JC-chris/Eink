"""Licentie aan basisstation-kant: wekelijkse check-in, uitschakeling, vervalsing, klok."""

import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from eink_basestation.agent import Agent
from eink_basestation.config import Config, hash_password
from eink_basestation.license import LicenseManager
from eink_basestation.radio import SimulatedRadio
from eink_basestation.webui import create_webui
from eink_cloud.main import create_app

LABEL = "C0:FF:EE:00:00:07"
WEEK = 7 * 86400


class Clock:
    def __init__(self):
        import time

        self.t = time.time()

    def __call__(self):
        return self.t


@pytest.fixture
def env(tmp_path):
    cloud = create_app("sqlite://", "adm", monitor_interval_s=None)
    admin = TestClient(cloud, headers={"Authorization": "Bearer adm"})
    admin.post("/v1/manage/customers", json={"id": "klant", "name": "Klant", "monthly_price_cents": 100})
    store = admin.post("/v1/admin/stores", json={"id": "winkel", "name": "Winkel", "customer_id": "klant", "price_source": "manual"}).json()
    bs = admin.post("/v1/admin/stores/winkel/basestations", json={"id": "bs-1"}).json()
    pos = TestClient(cloud, headers={"Authorization": f"Bearer {store['api_key']}"})
    pos.post("/v1/stores/winkel/labels", json={"label_id": LABEL, "display_type": "bwr_2_13"})

    config = Config(server="http://testserver", token=bs["token"], password_hash=hash_password("wachtwoord1"))
    path = tmp_path / "config.json"
    config.save(path)
    clock = Clock()
    lic = LicenseManager(config, path, clock=clock)
    factory = lambda c: TestClient(cloud, headers={"Authorization": f"Bearer {c.token}"})  # noqa: E731
    radio = SimulatedRadio()
    radio.add_label(LABEL)
    agent = Agent(factory(config), radio, license=lic)
    return agent, lic, clock, config, path, admin, factory


def test_first_contact_pins_key_and_activates(env):
    agent, lic, _clock, config, path, *_ = env
    assert lic.state().status == "missing"
    agent.heartbeat()
    assert config.license_public_key and config.basestation_id == "bs-1"
    assert Config.load(path).license_public_key == config.license_public_key
    assert lic.state().status == "valid"
    # Na herstart (zonder internet) is de licentie er nog.
    assert LicenseManager(Config.load(path), path, clock=lic.clock).state().status == "valid"


def test_weekly_checkin_required(env):
    agent, lic, clock, _config, _path, admin, _f = env
    agent.heartbeat()
    clock.t += 5 * 86400 + 60
    assert lic.state().status == "expiring"
    clock.t += 2 * 86400
    state = lic.state()
    assert state.status == "expired" and not state.operational

    # Zonder licentie wordt niets verstuurd, ook al staat er werk klaar in de cloud.
    agent._last_heartbeat = float("inf")  # simuleer: cloud onbereikbaar, geen nieuwe heartbeat
    assert agent.run_once() == 0 and "week" in agent.status.last_error

    # Verbinding terug → nieuwe licentie → weer in bedrijf.
    agent._last_heartbeat = float("-inf")
    agent.run_once()
    assert lic.state().status == "valid"


def test_suspended_system(env):
    agent, lic, _clock, config, path, admin, factory = env
    agent.heartbeat()
    admin.post("/v1/manage/customers/klant/suspend", json={"reason": "opgezegd"})
    agent._last_heartbeat = float("-inf")
    assert agent.run_once() == 1  # ook een ongekoppeld label krijgt "Prijs aan de kassa"
    state = lic.state()
    assert state.status == "suspended" and state.operational and not state.prices_editable

    ui = TestClient(create_webui(config, path, agent, factory, license=lic))
    ui.post("/login", data={"password": "wachtwoord1"})
    page = ui.get("/producten").text
    assert "Systeem uitgeschakeld" in page and "Product toevoegen" not in page
    r = ui.post("/producten", data={"sku": "1", "name": "Brood", "price": "2,00"})
    assert "uitgeschakeld" in r.text


def test_forged_and_foreign_licenses_rejected(env):
    agent, lic, clock, config, *_ = env
    agent.heartbeat()
    good = lic.lease

    # Eigen server met eigen sleutel: handtekening klopt niet.
    pirate = Ed25519PrivateKey.generate()
    import base64

    raw = json.dumps({"v": 1, "basestation_id": "bs-1", "store_id": "winkel", "status": "active",
                      "issued_at": int(clock.t), "valid_until": int(clock.t) + 10 * WEEK}).encode()
    b = lambda d: base64.urlsafe_b64encode(d).rstrip(b"=").decode()  # noqa: E731
    lic.update({"payload": b(raw), "signature": b(pirate.sign(raw))})
    assert "handtekening ongeldig" in lic.error and lic.lease == good

    # Gemanipuleerde inhoud (geldigheid opgerekt) met de echte handtekening.
    payload = json.loads(base64.urlsafe_b64decode(good["payload"] + "=="))
    payload["valid_until"] += 52 * WEEK
    lic.update({"payload": b(json.dumps(payload).encode()), "signature": good["signature"]})
    assert "handtekening ongeldig" in lic.error

    # Licentie van een ander basisstation.
    config.basestation_id = "bs-ander"
    lic.update(good)
    assert "ander basisstation" in lic.error
    assert lic.state().status == "valid"  # oude geldige licentie blijft staan


def test_clock_rollback_detected(env):
    agent, lic, clock, *_ = env
    agent.heartbeat()
    clock.t += 3 * 86400
    assert lic.state().status == "valid"
    clock.t -= 2 * 86400  # klok terugzetten om de licentie te rekken
    assert lic.state().status == "invalid" and "klok" in lic.state().text


def test_device_clock_skew_does_not_matter(env):
    agent, lic, clock, *_ = env
    clock.t += 30 * 86400  # klok van het apparaat loopt een maand voor
    agent.heartbeat()
    assert lic.state().status == "valid"
    clock.t += WEEK + 1
    assert lic.state().status == "expired"
