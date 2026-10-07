"""Ondertekende licenties voor basisstations (verbindingslaag met het managementsysteem).

Bij elke check-in krijgt een basisstation een licentie die `LEASE_DAYS` geldig is, ondertekend met
onze Ed25519-sleutel. Het basisstation controleert de handtekening met de publieke sleutel die in
de fabriek is ingesteld. Gevolg:

- Geen verbinding met ons gedurende een week → licentie verlopen → basisstation stopt.
- Abonnement uitgeschakeld → licentie met status "suspended" → basisstation stopt.
- Basisstation naar een eigen server laten wijzen helpt niet: die kan geen geldige licentie maken.
"""

import base64
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .models import BaseStation, Store

log = logging.getLogger("eink_cloud.licensing")

LEASE_DAYS = 7
SUPPORT_CONTACT = os.environ.get("EINK_SUPPORT_CONTACT", "support@example.com")


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def load_or_create_key(path: str | None) -> Ed25519PrivateKey:
    """Productie: sleutel uit een secret store/HSM. Ontwikkeling: wordt aangemaakt als hij ontbreekt."""
    if path is None:
        return Ed25519PrivateKey.generate()
    p = Path(path)
    if p.exists():
        key = serialization.load_pem_private_key(p.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise RuntimeError(f"{path} is geen Ed25519-sleutel")
        return key
    key = Ed25519PrivateKey.generate()
    p.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    os.chmod(p, 0o600)
    log.warning("nieuwe licentiesleutel aangemaakt in %s — bewaar deze veilig", path)
    return key


def public_key_b64(key: Ed25519PrivateKey) -> str:
    return b64(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def issue_lease(key: Ed25519PrivateKey, bs: BaseStation, store: Store, now: datetime, message: str | None = None) -> dict:
    valid_until = now + timedelta(days=LEASE_DAYS)
    payload = {
        "v": 1,
        "basestation_id": bs.id,
        "store_id": store.id,
        "status": store.service_state,
        # Tijden in de database zijn naïeve UTC.
        "issued_at": int(now.replace(tzinfo=UTC).timestamp()),
        "valid_until": int(valid_until.replace(tzinfo=UTC).timestamp()),
        "message": message,
        "support": SUPPORT_CONTACT,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    bs.license_valid_until = valid_until
    return {"payload": b64(raw), "signature": b64(key.sign(raw))}
