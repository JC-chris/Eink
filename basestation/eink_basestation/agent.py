"""Basisstation-agent: heartbeat, jobs ophalen, via radio versturen, resultaat melden."""

import argparse
import base64
import logging
import os
import time
from dataclasses import asdict

import httpx

from . import __version__
from .radio import LabelStatus, NordicEslRadio, RadioBackend, SimulatedRadio

log = logging.getLogger("eink_basestation")


def _cpu_temp() -> float | None:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read()) / 1000
    except (OSError, ValueError):
        return None


class Agent:
    def __init__(self, client: httpx.Client, radio: RadioBackend, heartbeat_interval_s: float = 30):
        self.client = client
        self.radio = radio
        self.heartbeat_interval_s = heartbeat_interval_s
        self.started = time.monotonic()
        self._last_heartbeat = float("-inf")

    def heartbeat(self) -> None:
        body = {
            "software_version": __version__,
            "uptime_s": int(time.monotonic() - self.started),
            "cpu_temp_c": _cpu_temp(),
            "labels_seen": [asdict(s) for s in self.radio.scan()],
        }
        self.client.post("/v1/basestation/heartbeat", json=body).raise_for_status()
        self._last_heartbeat = time.monotonic()

    def process_jobs(self, limit: int = 20) -> int:
        resp = self.client.get("/v1/basestation/jobs", params={"limit": limit})
        resp.raise_for_status()
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
            self.client.post(f"/v1/basestation/jobs/{job['job_id']}/result", json=body).raise_for_status()
        return len(jobs)

    def run_once(self) -> int:
        if time.monotonic() - self._last_heartbeat >= self.heartbeat_interval_s:
            self.heartbeat()
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
                log.warning("cloud niet bereikbaar (%s), opnieuw over %.0fs", exc, backoff)
                backoff = min(backoff * 2, 60)
            time.sleep(backoff)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--server", default=os.environ.get("EINK_SERVER", "http://localhost:8000"))
    p.add_argument("--token", default=os.environ.get("EINK_BASESTATION_TOKEN"), required="EINK_BASESTATION_TOKEN" not in os.environ)
    p.add_argument("--simulate", metavar="LABEL_ID", nargs="*", help="gebruik gesimuleerde radio met deze labels")
    p.add_argument("--device", default="/dev/ttyACM0", help="seriële poort van de nRF54L15")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.simulate is not None:
        radio = SimulatedRadio()
        for label_id in args.simulate:
            radio.add_label(label_id)
    else:
        radio = NordicEslRadio(args.device)
    client = httpx.Client(base_url=args.server, headers={"Authorization": f"Bearer {args.token}"}, timeout=30)
    Agent(client, radio).run_forever()


if __name__ == "__main__":
    main()
