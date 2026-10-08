"""Read image format and size from PNG/JPEG/WebP headers without third-party libraries."""
from __future__ import annotations

import struct
from pathlib import Path

from .util import ForgeError


def image_info(path):
    data = Path(path).read_bytes()[:65536]
    if data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return {"format": "png", "width": width, "height": height, "alpha": data[25] in (4, 6)}
    if data.startswith(b"\xff\xd8"):
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return {"format": "jpeg", "width": width, "height": height, "alpha": False}
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + length
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return {"format": "webp", "width": width, "height": height, "alpha": bool(data[20] & 0x10)}
        if chunk == b"VP8 ":
            width, height = struct.unpack("<HH", data[26:30])
            return {"format": "webp", "width": width & 0x3FFF, "height": height & 0x3FFF, "alpha": False}
        if chunk == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return {"format": "webp", "width": (bits & 0x3FFF) + 1, "height": ((bits >> 14) & 0x3FFF) + 1, "alpha": True}
    raise ForgeError("Unsupported or unreadable reference image (PNG, JPEG or WebP required): %s" % path)
