"""Instellingen van het basisstation, bewaard als JSON (alleen leesbaar voor root)."""

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("EINK_BASESTATION_CONFIG", "/etc/eink-basestation/config.json"))
PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    except ValueError:
        return False
    return hmac.compare_digest(actual, digest)


@dataclass
class Config:
    server: str = "https://cloud.example.com"
    token: str = ""
    web_port: int = 8080
    password_hash: str = ""
    session_secret: str = field(default_factory=lambda: secrets.token_hex(32))
    # Installatie-hotspot als er geen netwerk is (SSID + wachtwoord op de sticker).
    hotspot_enabled: bool = True
    hotspot_ssid: str = ""
    hotspot_password: str = ""
    # Verbindingslaag managementsysteem: in de fabriek gezet (anders vastgezet bij eerste verbinding).
    license_public_key: str = ""
    basestation_id: str = ""
    # Importmap: weegschaal-/kassasoftware zet hier een prijslijst-export neer (bv. via een netwerkshare).
    import_enabled: bool = False
    import_dir: str = "/var/lib/eink-basestation/import"

    @classmethod
    def load(cls, path: Path) -> "Config":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(path)  # atomair: geen half geschreven config bij stroomuitval

    def ensure_hotspot(self) -> None:
        """Uniek per apparaat; in productie zet de fabriek dit op de sticker."""
        if not self.hotspot_ssid:
            self.hotspot_ssid = f"Eink-{secrets.token_hex(2).upper()}"
        if not self.hotspot_password:
            self.hotspot_password = secrets.token_urlsafe(9)

    def ensure_password(self) -> str | None:
        """Geen standaardwachtwoorden (EN 18031): genereer er een per apparaat.

        In productie zet de fabriek dit wachtwoord in de config en print het op de sticker.
        Geeft het nieuwe wachtwoord terug als er een is aangemaakt.
        """
        if self.password_hash:
            return None
        password = secrets.token_urlsafe(9)
        self.password_hash = hash_password(password)
        return password
