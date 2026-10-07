"""Minimale frame-decoder (zelfde formaat als backend/eink_cloud/imageformat.py en de firmware)."""

import struct
import zlib

HEADER = struct.Struct("<2sBBHHBBII")


def rle_decode(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        c = data[i]
        i += 1
        if c & 0x80:
            out += bytes([data[i]]) * ((c & 0x7F) + 1)
            i += 1
        else:
            out += data[i : i + c + 1]
            i += c + 1
    return bytes(out)


def decoded_crc(frame: bytes) -> int:
    """Wat een label na decoderen als CRC zou terugmelden. Gooit ValueError bij een kapot frame."""
    magic, version, _enc, w, h, bpp, _pal, crc, length = HEADER.unpack_from(frame)
    if magic != b"EI" or version != 1:
        raise ValueError("onbekend frameformaat")
    raw = rle_decode(frame[HEADER.size : HEADER.size + length])
    if len(raw) != (w * h * bpp + 7) // 8:
        raise ValueError("verkeerde lengte pixeldata")
    actual = zlib.crc32(raw)
    if actual != crc:
        raise ValueError("CRC-fout")
    return actual
