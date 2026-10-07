import pytest
from fastapi.testclient import TestClient

from eink_cloud.main import create_app

ADMIN = "admin-test-token"


@pytest.fixture
def app():
    return create_app("sqlite://", ADMIN, monitor_interval_s=None)


@pytest.fixture
def admin(app):
    return TestClient(app, headers={"Authorization": f"Bearer {ADMIN}"})


@pytest.fixture
def store(app, admin):
    """Winkel met één basisstation; geeft (kassa-client, basisstation-client) terug."""
    s = admin.post("/v1/admin/stores", json={"id": "slagerij-jansen", "name": "Slagerij Jansen"}).json()
    bs = admin.post("/v1/admin/stores/slagerij-jansen/basestations", json={"id": "bs-1"}).json()
    pos = TestClient(app, headers={"Authorization": f"Bearer {s['api_key']}"})
    station = TestClient(app, headers={"Authorization": f"Bearer {bs['token']}"})
    return pos, station
