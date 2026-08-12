"""Minimal PNG reader/writer and image comparison, stdlib only.

Playwright writes 8-bit non-interlaced PNGs, which is a small enough subset of
the format to decode with ``zlib`` alone. Doing it here avoids adding Pillow as
a dependency just to compare screenshots.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunks(data: bytes):
    offset = 8
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        yield kind, payload
        offset += 12 + length


def read_png(path: Path) -> tuple[int, int, bytearray]:
    """Return ``(width, height, rgba)`` with 4 bytes per pixel."""
    data = Path(path).read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f"{path} is not a PNG")

    width = height = bit_depth = colour_type = interlace = None
    idat = bytearray()
    for kind, payload in _chunks(data):
        if kind == b"IHDR":
            width, height, bit_depth, colour_type, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
        elif kind == b"IDAT":
            idat.extend(payload)
        elif kind == b"IEND":
            break

    if bit_depth != 8 or interlace != 0 or colour_type not in (2, 6):
        raise ValueError(
            f"{path}: unsupported PNG (bit_depth={bit_depth}, "
            f"colour_type={colour_type}, interlace={interlace})"
        )

    channels = 4 if colour_type == 6 else 3
    raw = zlib.decompress(bytes(idat))
    stride = width * channels

    out = bytearray(width * height * 4)
    previous = bytearray(stride)
    pos = 0
    for row in range(height):
        filter_type = raw[pos]
        pos += 1
        line = bytearray(raw[pos : pos + stride])
        pos += stride
        _unfilter(filter_type, line, previous, channels)
        if channels == 4:
            out[row * stride : row * stride + stride] = line
        else:
            base = row * width * 4
            for x in range(width):
                out[base + x * 4 : base + x * 4 + 3] = line[x * 3 : x * 3 + 3]
                out[base + x * 4 + 3] = 255
        previous = line
    return width, height, out


def _unfilter(filter_type: int, line: bytearray, previous: bytearray, bpp: int) -> None:
    if filter_type == 0:
        return
    if filter_type == 1:
        for i in range(bpp, len(line)):
            line[i] = (line[i] + line[i - bpp]) & 0xFF
    elif filter_type == 2:
        for i in range(len(line)):
            line[i] = (line[i] + previous[i]) & 0xFF
    elif filter_type == 3:
        for i in range(len(line)):
            left = line[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
    elif filter_type == 4:
        for i in range(len(line)):
            a = line[i - bpp] if i >= bpp else 0
            b = previous[i]
            c = previous[i - bpp] if i >= bpp else 0
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            line[i] = (line[i] + pred) & 0xFF
    else:
        raise ValueError(f"unknown PNG filter type {filter_type}")


def write_png(path: Path, width: int, height: int, rgba: bytes) -> None:
    raw = bytearray()
    stride = width * 4
    for row in range(height):
        raw.append(0)  # filter: none
        raw.extend(rgba[row * stride : (row + 1) * stride])

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    Path(path).write_bytes(
        PNG_SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


class SizeMismatch(Exception):
    """Raised when two screenshots have different dimensions."""


def compare(
    baseline: Path, candidate: Path, channel_tolerance: int = 0
) -> tuple[int, int, bytes | None, tuple[int, int]]:
    """Compare two PNGs.

    Returns ``(differing_pixels, total_pixels, diff_rgba_or_None, (w, h))``.

    ``channel_tolerance`` is the per-channel absolute difference below which a
    pixel counts as equal. Captures on this harness are byte-identical between
    runs, so the default is 0 — any difference is a real difference.
    """
    bw, bh, bpix = read_png(baseline)
    cw, ch, cpix = read_png(candidate)
    if (bw, bh) != (cw, ch):
        raise SizeMismatch(f"baseline is {bw}x{bh}, candidate is {cw}x{ch}")

    total = bw * bh
    differing = 0
    diff = bytearray(total * 4)
    for i in range(total):
        o = i * 4
        delta = max(
            abs(bpix[o] - cpix[o]),
            abs(bpix[o + 1] - cpix[o + 1]),
            abs(bpix[o + 2] - cpix[o + 2]),
            abs(bpix[o + 3] - cpix[o + 3]),
        )
        if delta > channel_tolerance:
            differing += 1
            diff[o : o + 4] = b"\xff\x00\x00\xff"      # changed pixels in red
        else:
            grey = (bpix[o] + bpix[o + 1] + bpix[o + 2]) // 3
            faded = 200 + grey // 5                    # unchanged, faded out
            diff[o : o + 4] = bytes((faded, faded, faded, 255))

    return differing, total, (bytes(diff) if differing else None), (bw, bh)
