import random

import pytest

from eink_cloud.imageformat import (
    build_frame, decode_frame, pack_pixels, rle_decode, rle_encode, unpack_pixels,
)

CASES = [b"", b"\x00", b"\x01\x02", b"\x05" * 300, bytes(range(256)) * 2, b"\x00\x00\x01" * 100]


@pytest.mark.parametrize("data", CASES)
def test_rle_roundtrip(data):
    assert rle_decode(rle_encode(data)) == data


def test_rle_roundtrip_random():
    rng = random.Random(1)
    for _ in range(200):
        data = bytes(rng.choice([0, 0, 0, 255, rng.randrange(256)]) for _ in range(rng.randrange(1000)))
        assert rle_decode(rle_encode(data)) == data


@pytest.mark.parametrize("bpp", [1, 2, 4])
def test_pack_roundtrip(bpp):
    rng = random.Random(bpp)
    idx = bytes(rng.randrange(1 << bpp) for _ in range(101))
    assert unpack_pixels(pack_pixels(idx, bpp), bpp, len(idx)) == idx


def test_pack_msb_first():
    assert pack_pixels(bytes([1, 0, 0, 0, 0, 0, 0, 1]), 1) == b"\x81"
    assert pack_pixels(bytes([3, 2, 1, 0]), 2) == b"\xe4"


def test_frame_roundtrip_and_corruption():
    frame = build_frame(bytes([1] * 64 + [2] * 64), 16, 8, 2, 2)
    blob = frame.encode()
    assert decode_frame(blob) == frame
    broken = bytearray(blob)
    broken[-1] ^= 0xFF
    with pytest.raises(ValueError):
        decode_frame(bytes(broken))
