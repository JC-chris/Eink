"""Radio-laag. De agent praat alleen met RadioBackend; de echte nRF54L15 komt later."""

import random
from dataclasses import dataclass, field
from typing import Protocol

from .frame import decoded_crc


@dataclass
class LabelStatus:
    label_id: str
    rssi: int | None = None
    battery_mv: int | None = None
    temperature_c: float | None = None
    firmware_version: str | None = None
    displayed_crc: int | None = None


@dataclass
class SendResult:
    success: bool
    status: LabelStatus | None = None
    error: str | None = None


class RadioBackend(Protocol):
    def scan(self) -> list[LabelStatus]:
        """Labels die sinds de vorige scan gehoord zijn, met telemetrie."""

    def send_image(self, label_id: str, frame: bytes) -> SendResult:
        """Verstuur een frame; blokkeert tot het label bevestigt of opgeeft."""


@dataclass
class SimulatedLabel:
    status: LabelStatus
    reachable: bool = True


@dataclass
class SimulatedRadio:
    """Doet alsof er labels in bereik zijn. Decodeert echt, zodat formaatfouten opvallen."""

    labels: dict[str, SimulatedLabel] = field(default_factory=dict)
    failure_rate: float = 0.0
    rng: random.Random = field(default_factory=random.Random)

    def add_label(self, label_id: str, battery_mv: int = 3000, rssi: int = -60, temperature_c: float = 4.0) -> None:
        self.labels[label_id] = SimulatedLabel(
            LabelStatus(label_id, rssi=rssi, battery_mv=battery_mv, temperature_c=temperature_c, firmware_version="0.1.0")
        )

    def scan(self) -> list[LabelStatus]:
        return [l.status for l in self.labels.values() if l.reachable]

    def send_image(self, label_id: str, frame: bytes) -> SendResult:
        label = self.labels.get(label_id)
        if label is None or not label.reachable:
            return SendResult(False, error="label niet in bereik")
        if self.rng.random() < self.failure_rate:
            return SendResult(False, label.status, error="geen bevestiging van label (gesimuleerd)")
        try:
            label.status.displayed_crc = decoded_crc(frame)
        except ValueError as exc:
            return SendResult(False, label.status, error=f"label kon frame niet decoderen: {exc}")
        label.status.battery_mv = (label.status.battery_mv or 3000) - 1  # elke refresh kost wat
        return SendResult(True, label.status)


class NordicEslRadio:
    """Koppeling met de nRF54L15 radio-coprocessor over UART (nog te bouwen).

    Plan: de coprocessor draait nRF Connect SDK `central_esl` met een eenvoudige
    commando-set over UART (SLIP-frames): SCAN, PUSH_IMAGE <id> <frame>, LED <id>,
    met asynchrone events voor telemetrie. Zie docs/03-basisstation.md en docs/04-radioprotocol.md.
    """

    def __init__(self, device: str = "/dev/ttyACM0", baudrate: int = 1_000_000):
        self.device, self.baudrate = device, baudrate

    def scan(self) -> list[LabelStatus]:
        raise NotImplementedError("NordicEslRadio is nog niet geïmplementeerd")

    def send_image(self, label_id: str, frame: bytes) -> SendResult:
        raise NotImplementedError("NordicEslRadio is nog niet geïmplementeerd")
