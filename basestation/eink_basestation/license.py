"""Licentie van het basisstation (de verbindingslaag met het managementsysteem).

Elke check-in levert een door de cloud ondertekende licentie op die 7 dagen geldig is. Het
basisstation werkt alleen met een geldige licentie:

- geen verbinding met het managementsysteem gedurende een week → licentie verlopen → stoppen;
- abonnement uitgeschakeld → licentie met status "suspended" → alleen nog de "buiten dienst"-
  beelden van de cloud verwerken, prijsbeheer uit;
- een andere server instellen helpt niet: die kan geen licentie met onze sleutel ondertekenen;
- klok terugzetten helpt niet: de hoogst geziene tijd wordt bewaard.

De geldigheid telt vanaf het moment van ontvangst met de eigen klok (duur = valid_until -
issued_at). Een afwijkende klok van het basisstation maakt de licentie dus niet onterecht ongeldig.

De publieke sleutel wordt in de fabriek in de config gezet. Ontbreekt hij (ontwikkeling), dan
wordt hij bij de eerste verbinding opgehaald en vastgezet (trust on first use).
"""

import base64
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .config import Config

log = logging.getLogger("eink_basestation.license")

WARN_BEFORE_S = 2 * 86400
CLOCK_TOLERANCE_S = 3600


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class LicenseError(Exception):
    pass


def verify(lease: dict, public_key_b64: str) -> dict:
    """Controleert de handtekening en geeft de inhoud terug."""
    try:
        raw = _unb64(lease["payload"])
        Ed25519PublicKey.from_public_bytes(_unb64(public_key_b64)).verify(_unb64(lease["signature"]), raw)
        payload = json.loads(raw)
    except InvalidSignature:
        raise LicenseError("handtekening ongeldig — licentie komt niet van het managementsysteem") from None
    except (KeyError, ValueError, TypeError) as exc:
        raise LicenseError(f"licentie onleesbaar: {exc}") from None
    if payload.get("v") != 1:
        raise LicenseError("onbekende licentieversie")
    return payload


@dataclass
class LicenseState:
    status: str  # valid | expiring | suspended | expired | missing | invalid
    text: str
    valid_until: float | None = None  # lokale tijd
    message: str | None = None
    support: str | None = None

    @property
    def operational(self) -> bool:
        """Mag de agent jobs van de cloud verwerken? (Bij suspended: alleen buiten-dienstbeelden.)"""
        return self.status in ("valid", "expiring", "suspended")

    @property
    def prices_editable(self) -> bool:
        return self.status in ("valid", "expiring")


class LicenseManager:
    def __init__(self, config: Config, config_path: Path, clock=time.time):
        self.config, self.config_path, self.clock = config, config_path, clock
        self.state_path = config_path.with_name("license.json")
        self.lease: dict | None = None
        self.payload: dict | None = None
        self.received_at: float = 0
        self.high_water: float = 0
        self._saved_high_water: float = 0
        self.error: str | None = None
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return
        self.high_water = self._saved_high_water = float(data.get("high_water", 0))
        self.received_at = float(data.get("received_at", 0))
        lease = data.get("lease")
        if lease and self.config.license_public_key:
            try:
                self.payload, self.lease = verify(lease, self.config.license_public_key), lease
            except LicenseError as exc:
                self.error = str(exc)

    def _save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"lease": self.lease, "received_at": self.received_at, "high_water": self.high_water}))
        os.chmod(tmp, 0o600)
        tmp.replace(self.state_path)
        self._saved_high_water = self.high_water

    @property
    def needs_public_key(self) -> bool:
        return not self.config.license_public_key

    def pin_public_key(self, key_b64: str) -> None:
        log.warning("publieke licentiesleutel vastgezet bij eerste verbinding (TOFU)")
        self.config.license_public_key = key_b64
        self.config.save(self.config_path)

    def update(self, lease: dict | None) -> None:
        """Nieuwe licentie uit het heartbeat-antwoord."""
        if not lease:
            self.error = "server gaf geen licentie"
            return
        try:
            payload = verify(lease, self.config.license_public_key)
            if self.config.basestation_id and payload["basestation_id"] != self.config.basestation_id:
                raise LicenseError("licentie is voor een ander basisstation")
        except LicenseError as exc:
            self.error = str(exc)
            log.error("licentie geweigerd: %s", exc)
            return
        if not self.config.basestation_id:
            self.config.basestation_id = payload["basestation_id"]
            self.config.save(self.config_path)
        self.payload, self.lease, self.error = payload, lease, None
        self.received_at = self.clock()
        self.high_water = max(self.high_water, self.received_at)
        self._save()

    def state(self) -> LicenseState:
        now = self.clock()
        if self.error and self.payload is None:
            return LicenseState("invalid", f"Geen geldige licentie: {self.error}")
        if self.payload is None:
            return LicenseState("missing", "Nog geen verbinding gehad met het managementsysteem")
        p = self.payload
        valid_until = self.received_at + (p["valid_until"] - p["issued_at"])
        if now < self.high_water - CLOCK_TOLERANCE_S:
            return LicenseState("invalid", "De klok van het basisstation staat terug; maak verbinding om te herstellen",
                                valid_until, support=p.get("support"))
        if self.high_water < now:
            self.high_water = now
            if now - self._saved_high_water > 300:  # elke 5 minuten bewaren is genoeg
                self._save()
        if now >= valid_until:
            return LicenseState("expired", "Het basisstation heeft langer dan een week geen verbinding gemaakt met het "
                                "managementsysteem en is gestopt. Controleer de internetverbinding.",
                                valid_until, p.get("message"), p.get("support"))
        if p["status"] == "suspended":
            return LicenseState("suspended", p.get("message") or "Het systeem is uitgeschakeld.",
                                valid_until, p.get("message"), p.get("support"))
        if valid_until - now < WARN_BEFORE_S:
            return LicenseState("expiring", "Maak binnenkort verbinding met het managementsysteem, anders stopt het systeem.",
                                valid_until, p.get("message"), p.get("support"))
        return LicenseState("valid", "Licentie geldig", valid_until, p.get("message"), p.get("support"))
