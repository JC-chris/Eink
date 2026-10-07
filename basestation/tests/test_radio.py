import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from eink_basestation.radio import SimulatedRadio  # noqa: E402
from eink_cloud.imageformat import build_frame  # noqa: E402


def test_simulated_label_decodes_frame():
    radio = SimulatedRadio()
    radio.add_label("L1")
    frame = build_frame(bytes([0, 1, 2, 3] * 32), 16, 8, 2, 2)
    result = radio.send_image("L1", frame.encode())
    assert result.success and result.status.displayed_crc == frame.crc32


def test_corrupt_frame_is_rejected():
    radio = SimulatedRadio()
    radio.add_label("L1")
    blob = bytearray(build_frame(bytes(128), 16, 8, 2, 2).encode())
    blob[-1] ^= 1
    result = radio.send_image("L1", bytes(blob))
    assert not result.success and "CRC" in result.error


def test_unreachable_label():
    assert not SimulatedRadio().send_image("onbekend", b"").success
