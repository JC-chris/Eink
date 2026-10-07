import asyncio
import contextlib
import logging
import os

from fastapi import FastAPI

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .api import admin, basestation, beheer, manage, monitoring, pos
from .db import make_sessionmaker
from .licensing import load_or_create_key
from .monitoring import evaluate_alerts
from .security import sign

log = logging.getLogger("eink_cloud")


def create_app(database_url: str | None = None, admin_token: str | None = None, monitor_interval_s: float | None = 60,
               license_key: Ed25519PrivateKey | None = None) -> FastAPI:
    database_url = database_url or os.environ.get("EINK_DATABASE_URL", "sqlite:///eink.db")
    admin_token = admin_token or os.environ.get("EINK_ADMIN_TOKEN")
    if not admin_token:
        raise RuntimeError("EINK_ADMIN_TOKEN is niet gezet")
    if license_key is None:
        key_file = os.environ.get("EINK_LICENSE_KEY_FILE")
        if not key_file:
            log.warning("EINK_LICENSE_KEY_FILE niet gezet: tijdelijke licentiesleutel, licenties ongeldig na herstart")
        license_key = load_or_create_key(key_file)

    async def monitor_loop(app: FastAPI) -> None:
        while True:
            await asyncio.sleep(monitor_interval_s)
            try:
                with app.state.sessionmaker() as session:
                    for alert in evaluate_alerts(session):
                        log.warning("open alert %s %s: %s", alert.kind, alert.subject_id, alert.message)
            except Exception:
                log.exception("monitoring mislukt")

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(monitor_loop(app)) if monitor_interval_s else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Eink cloud", version="0.1.0", lifespan=lifespan,
                  description="Kassa-API, label-updates en monitoring voor e-ink prijslabels.")
    app.state.sessionmaker = make_sessionmaker(database_url)
    app.state.admin_token = admin_token
    app.state.license_key = license_key
    app.state.session_secret = os.environ.get("EINK_SESSION_SECRET") or sign(admin_token, "beheer-sessies")
    for module in (admin, pos, basestation, monitoring, manage):
        app.include_router(module.router)
    beheer.install(app)

    @app.get("/health", tags=["monitoring"])
    def health():
        return {"status": "ok"}

    return app


def __getattr__(name: str):
    # `uvicorn eink_cloud.main:app` maakt de app pas aan als hij gevraagd wordt.
    if name == "app":
        return create_app()
    raise AttributeError(name)
