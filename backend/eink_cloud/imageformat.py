"""Beeldformaat dat via het basisstation naar het label gaat.

Spiegelbeeld van firmware/label/src/eink_image.h — wijzigingen altijd in beide doorvoeren.
"""

import struct
import zlib
from dataclasses import dataclass

MAGIC = b"EI"
VERSION = 1
ENCODING_RLE = 1
HEADER = struct.Struct("<2sBBHHBBII")  # 18 bytes


def pack_pixels(indices: bytes, bits_per_pixel: int) -> bytes:
    """Pak palet-indexen (1 byte per pixel) samen, MSB-eerst."""
    per_byte = 8 // bits_per_pixel
    out = bytearray()
    for i in range(0, len(indices), per_byte):
        b = 0
        chunk = indices[i : i + per_byte]
        for j in range(per_byte):
            v = chunk[j] if j < len(chunk) else 0
            b = (b << bits_per_pixel) | v
        out.append(b)
    return bytes(out)


def unpack_pixels(data: bytes, bits_per_pixel: int, count: int) -> bytes:
    per_byte = 8 // bits_per_pixel
    mask = (1 << bits_per_pixel) - 1
    out = bytearray()
    for b in data:
        for j in range(per_byte):
            out.append((b >> (8 - bits_per_pixel * (j + 1))) & mask)
    return bytes(out[:count])


def rle_encode(data: bytes) -> bytes:
    """PackBits-variant: c&0x80 -> herhaal volgende byte (c&0x7F)+1 keer, anders c+1 literals."""
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        run = 1
        while i + run < n and run < 128 and data[i + run] == data[i]:
            run += 1
        if run >= 2:
            out += bytes((0x80 | (run - 1), data[i]))
            i += run
            continue
        start = i
        while i < n and i - start < 128:
            if i + 1 < n and data[i + 1] == data[i]:
                break
            i += 1
        if i == start:  # alleen mogelijk aan het eind van een korte reeks
            i += 1
        out.append(i - start - 1)
        out += data[start:i]
    return bytes(out)


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


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    bits_per_pixel: int
    palette_id: int
    crc32: int
    raw: bytes  # gepakte, ongecomprimeerde pixeldata

    def encode(self) -> bytes:
        payload = rle_encode(self.raw)
        header = HEADER.pack(
            MAGIC, VERSION, ENCODING_RLE, self.width, self.height,
            self.bits_per_pixel, self.palette_id, self.crc32, len(payload),
        )
        return header + payload


def build_frame(indices: bytes, width: int, height: int, bits_per_pixel: int, palette_id: int) -> Frame:
    raw = pack_pixels(indices, bits_per_pixel)
    return Frame(width, height, bits_per_pixel, palette_id, zlib.crc32(raw), raw)


def decode_frame(blob: bytes) -> Frame:
    magic, version, encoding, w, h, bpp, pal, crc, length = HEADER.unpack_from(blob)
    if magic != MAGIC or version != VERSION or encoding != ENCODING_RLE:
        raise ValueError("onbekend frameformaat")
    raw = rle_decode(blob[HEADER.size : HEADER.size + length])
    if zlib.crc32(raw) != crc:
        raise ValueError("CRC-fout")
    return Frame(w, h, bpp, pal, crc, raw)
