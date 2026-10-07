"""Basisstation-agent: heartbeat, jobs ophalen, via radio versturen, resultaat melden."""

import argparse
import base64
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

from . import __version__
from .config import DEFAULT_PATH, Config
from .license import LicenseManager
from .radio import LabelStatus, NordicEslRadio, RadioBackend, SimulatedRadio

log = logging.getLogger("eink_basestation")


def _cpu_temp() -> float | None:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read()) / 1000
    except (OSError, ValueError):
        return None


@dataclass
class AgentStatus:
    """Toestand van de agent, getoond in de webinterface."""

    cloud_ok: bool = False
    last_contact: datetime | None = None
    last_error: str | None = None
    jobs_ok: int = 0
    jobs_failed: int = 0
    labels_seen: list[LabelStatus] = field(default_factory=list)


class Agent:
    def __init__(self, client: httpx.Client | None, radio: RadioBackend, heartbeat_interval_s: float = 30,
                 license: LicenseManager | None = None):
        self.client = client
        self.radio = radio
        self.license = license
        self.heartbeat_interval_s = heartbeat_interval_s
        self.started = time.monotonic()
        self.status = AgentStatus()
        self._last_heartbeat = float("-inf")

    @property
    def uptime_s(self) -> int:
        return int(time.monotonic() - self.started)

    def set_client(self, client: httpx.Client | None) -> None:
        """Nieuwe cloud-instellingen (via de webinterface): volgende ronde direct een heartbeat.

        Een lopende ronde maakt zijn werk af met de oude client (die houdt een lokale referentie).
        """
        self.client = client
        self._last_heartbeat = float("-inf")

    def _contact_ok(self) -> None:
        self.status.cloud_ok = True
        self.status.last_contact = datetime.now()
        self.status.last_error = None

    def heartbeat(self) -> None:
        client = self.client
        seen = self.radio.scan()
        body = {
            "software_version": __version__,
            "uptime_s": self.uptime_s,
            "cpu_temp_c": _cpu_temp(),
            "labels_seen": [asdict(s) for s in seen],
        }
        self.status.labels_seen = list(seen)
        if self.license is not None and self.license.needs_public_key:
            resp = client.get("/v1/basestation/license-key")
            resp.raise_for_status()
            self.license.pin_public_key(resp.json()["public_key"])
        resp = client.post("/v1/basestation/heartbeat", json=body)
        resp.raise_for_status()
        if self.license is not None:
            self.license.update(resp.json().get("license"))
        self._last_heartbeat = time.monotonic()
        self._contact_ok()

    def process_jobs(self, limit: int = 20) -> int:
        client = self.client
        resp = client.get("/v1/basestation/jobs", params={"limit": limit})
        resp.raise_for_status()
        self._contact_ok()
        jobs = resp.json()
        for job in jobs:
            result = self.radio.send_image(job["label_id"], base64.b64decode(job["frame_b64"]))
            status: LabelStatus | None = result.status
            body = {
                "success": result.success,
                "displayed_crc": status.displayed_crc if status else None,
                "error": result.error,
                "telemetry": asdict(status) if status else None,
            }
            log.info("job %s label %s: %s", job["job_id"], job["label_id"], "ok" if result.success else result.error)
            if result.success:
                self.status.jobs_ok += 1
            else:
                self.status.jobs_failed += 1
            client.post(f"/v1/basestation/jobs/{job['job_id']}/result", json=body).raise_for_status()
        return len(jobs)

    def run_once(self) -> int:
        if self.client is None:
            self.status.cloud_ok = False
            self.status.last_error = "niet geconfigureerd: stel server en token in via de webinterface"
            return 0
        if time.monotonic() - self._last_heartbeat >= self.heartbeat_interval_s:
            self.heartbeat()
        if self.license is not None:
            state = self.license.state()
            if not state.operational:
                # Zonder geldige licentie geen radioverkeer: wel blijven inchecken om er een te krijgen.
                self.status.last_error = state.text
                return 0
        return self.process_jobs()

    def run_forever(self, poll_interval_s: float = 2) -> None:
        backoff = poll_interval_s
        while True:
            try:
                handled = self.run_once()
                backoff = poll_interval_s
                if handled:
                    continue  # meteen door bij een volle wachtrij
            except httpx.HTTPError as exc:
                # Cloud onbereikbaar: labels blijven gewoon hun laatste beeld tonen.
                self.status.cloud_ok = False
                self.status.last_error = str(exc) or type(exc).__name__
                log.warning("cloud niet bereikbaar (%s), opnieuw over %.0fs", exc, backoff)
                backoff = min(backoff * 2, 60)
            time.sleep(backoff)


def main() -> None:
    import uvicorn

    from .cloud import default_client_factory
    from .network import NetworkWatchdog, SimulatedNetwork, detect_backend, start_watchdog
    from .webui import create_webui

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=DEFAULT_PATH)
    p.add_argument("--server", help="cloud-URL (wordt in de config opgeslagen)")
    p.add_argument("--token", help="basisstation-token (wordt in de config opgeslagen)")
    p.add_argument("--web-port", type=int, help="poort van de webinterface (standaard 8080)")
    p.add_argument("--simulate", metavar="LABEL_ID", nargs="*", help="gebruik gesimuleerde radio met deze labels")
    p.add_argument("--device", default="/dev/ttyACM0", help="seriële poort van de nRF54L15")
    p.add_argument("--network", choices=("auto", "networkmanager", "simulated"), default="auto",
                   help="netwerkbeheer: NetworkManager (apparaat) of simulatie; auto = simulatie bij --simulate")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # anders elke poll een logregel

    config = Config.load(args.config)
    for name in ("server", "token", "web_port"):
        if getattr(args, name) is not None:
            setattr(config, name, getattr(args, name))
    new_password = config.ensure_password()
    config.ensure_hotspot()
    config.save(args.config)
    if new_password:
        log.warning("Eerste wachtwoord webinterface: %s (wijzig via Instellingen)", new_password)

    if args.simulate is not None:
        radio = SimulatedRadio()
        for label_id in args.simulate:
            radio.add_label(label_id)
    else:
        radio = NordicEslRadio(args.device)
    license = LicenseManager(config, args.config)
    agent = Agent(default_client_factory(config) if config.token else None, radio, license=license)
    threading.Thread(target=agent.run_forever, name="agent", daemon=True).start()

    if args.network == "simulated" or (args.network == "auto" and args.simulate is not None):
        network = SimulatedNetwork()
    elif args.network == "networkmanager":
        from .network import NetworkManagerBackend

        network = NetworkManagerBackend()
    else:
        network = detect_backend()
    start_watchdog(NetworkWatchdog(network, config.hotspot_ssid, config.hotspot_password,
                                   enabled=lambda: config.hotspot_enabled))

    app = create_webui(config, args.config, agent, default_client_factory, network, license)
    uvicorn.run(app, host="0.0.0.0", port=config.web_port, log_level="warning")


if __name__ == "__main__":
    main()
