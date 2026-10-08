"""Pure-Python orthographic rasterizer, PNG writer, silhouette comparison and contact sheets.

Fast enough for review thumbnails and the individuality gate; real renders come from Blender in real mode.
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

from . import vecmath as vm

VIEWS = {
    # name: (yaw degrees about Z applied to the model before projecting onto X/Z, facing the camera)
    "front": 0.0,
    "side": 90.0,
    "three_quarter": 45.0,
    "back": 180.0,
}


def rotate_z(v, degrees):
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2])


def render(vertices, triangles, view="front", size=192, height=None, shade=True, window=None):
    """Return (width, height, pixels[rows][cols] greyscale 0..255, mask). Camera looks along +Y onto the model's front.

    window=(centre_x, centre_z, span) zooms onto a region (in the rotated view's X/Z), e.g. a face or hand close-up."""
    yaw = VIEWS.get(view, 0.0) if isinstance(view, str) else float(view)
    pts = [rotate_z(v, yaw) for v in vertices]
    w = h = size
    if window:
        cx, cz, span = window
        scale = (size - 1) / span
        screen = [((p[0] - cx) * scale + w / 2, (h - 1) / 2 - (p[2] - cz) * scale, p[1]) for p in pts]
    else:
        zs = [p[2] for p in pts]
        xs = [p[0] for p in pts]
        z0 = min(zs)
        span = max(height or 0.0, max(zs) - z0, max(xs) - min(xs), 1e-6) * 1.06
        cx = (max(xs) + min(xs)) / 2
        scale = (size - 1) / span
        screen = [((p[0] - cx) * scale + w / 2, (h - 1) - ((p[2] - z0) * scale + 0.03 * size), p[1]) for p in pts]
    depth = [[float("inf")] * w for _ in range(h)]
    pixels = [[0] * w for _ in range(h)]
    light = vm.normalize((0.4, -0.8, 0.45))
    for a, b, c in triangles:
        pa, pb, pc = screen[a], screen[b], screen[c]
        min_x = max(int(min(pa[0], pb[0], pc[0])), 0)
        max_x = min(int(max(pa[0], pb[0], pc[0])) + 1, w - 1)
        min_y = max(int(min(pa[1], pb[1], pc[1])), 0)
        max_y = min(int(max(pa[1], pb[1], pc[1])) + 1, h - 1)
        if min_x > max_x or min_y > max_y:
            continue
        area = (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pc[0] - pa[0]) * (pb[1] - pa[1])
        if abs(area) < 1e-12:
            continue
        if shade:
            n = vm.cross(vm.sub(pts[b], pts[a]), vm.sub(pts[c], pts[a]))
            nl = vm.length(n)
            intensity = 0.25 + 0.75 * abs(vm.dot(vm.mul(n, 1 / nl), light)) if nl > 0 else 0.6
            grey = int(40 + 200 * intensity)
        else:
            grey = 255
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                px, py = x + 0.5, y + 0.5
                w0 = ((pb[0] - px) * (pc[1] - py) - (pc[0] - px) * (pb[1] - py)) / area
                w1 = ((pc[0] - px) * (pa[1] - py) - (pa[0] - px) * (pc[1] - py)) / area
                w2 = 1 - w0 - w1
                if w0 < -1e-9 or w1 < -1e-9 or w2 < -1e-9:
                    continue
                d = w0 * pa[2] + w1 * pb[2] + w2 * pc[2]
                if d < depth[y][x]:
                    depth[y][x] = d
                    pixels[y][x] = grey
    mask = [[1 if pixels[y][x] else 0 for x in range(w)] for y in range(h)]
    return w, h, pixels, mask


def iou(mask_a, mask_b):
    inter = union = 0
    for ra, rb in zip(mask_a, mask_b):
        for a, b in zip(ra, rb):
            inter += a & b
            union += a | b
    return inter / union if union else 1.0


def mask_to_rle(mask):
    """Row-major run lengths starting with a 0-run; compact enough to store silhouettes as JSON."""
    flat = [v for row in mask for v in row]
    runs, current, count = [], 0, 0
    for v in flat:
        if v == current:
            count += 1
        else:
            runs.append(count)
            current, count = v, 1
    runs.append(count)
    return {"width": len(mask[0]), "height": len(mask), "runs": runs}


def rle_to_mask(rle):
    flat, value = [], 0
    for run in rle["runs"]:
        flat.extend([value] * run)
        value ^= 1
    w = rle["width"]
    return [flat[i:i + w] for i in range(0, len(flat), w)]


def write_png(path, pixels, rgb=False):
    """Write greyscale (rows of ints) or RGB (rows of (r,g,b)) PNG with stdlib zlib."""
    height = len(pixels)
    width = len(pixels[0])
    channels = len(pixels[0][0]) if rgb else 1
    raw = bytearray()
    for row in pixels:
        raw.append(0)
        if rgb:
            for px in row:
                raw += bytes(px)
        else:
            raw += bytes(max(0, min(255, int(v))) for v in row)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, {1: 0, 3: 2, 4: 6}[channels], 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)
    return Path(path)


def solid_png(path, size, colour):
    return write_png(path, [[tuple(colour)] * size for _ in range(size)], rgb=True)


# 5x7 bitmap font for labels (digits, upper-case letters and a few symbols).
_FONT = {
    "A": "01110100011000111111100011000110001", "B": "11110100011000111110100011000111110",
    "C": "01110100011000010000100001000101110", "D": "11110100011000110001100011000111110",
    "E": "11111100001000011110100001000011111", "F": "11111100001000011110100001000010000",
    "G": "01110100011000010111100011000101111", "H": "10001100011000111111100011000110001",
    "I": "01110001000010000100001000010001110", "J": "00111000100001000010000101001001100",
    "K": "10001100101010011000101001001010001", "L": "10000100001000010000100001000011111",
    "M": "10001110111010110101100011000110001", "N": "10001100011100110101100111000110001",
    "O": "01110100011000110001100011000101110", "P": "11110100011000111110100001000010000",
    "Q": "01110100011000110001101011001001101", "R": "11110100011000111110101001001010001",
    "S": "01111100001000001110000010000111110", "T": "11111001000010000100001000010000100",
    "U": "10001100011000110001100011000101110", "V": "10001100011000110001100010101000100",
    "W": "10001100011000110101101011010101010", "X": "10001100010101000100010101000110001",
    "Y": "10001100010101000100001000010000100", "Z": "11111000010001000100010001000011111",
    "0": "01110100011001110101110011000101110", "1": "00100011000010000100001000010001110",
    "2": "01110100010000100010001000100011111", "3": "11111000100010000010000011000101110",
    "4": "00010001100101010010111110001000010", "5": "11111100001111000001000011000101110",
    "6": "00110010001000011110100011000101110", "7": "11111000010001000100010000100001000",
    "8": "01110100011000101110100011000101110", "9": "01110100011000101111000010001001100",
    "-": "00000000000000011111000000000000000", "_": "00000000000000000000000000000011111",
    ".": "00000000000000000000000000110001100", " ": "0" * 35, "/": "00001000010001000100010001000010000",
    ":": "00000011000110000000011000110000000",
}


def draw_text(pixels, x, y, text, value=255):
    for ch in text.upper():
        bitmap = _FONT.get(ch, _FONT[" "])
        for row in range(7):
            for col in range(5):
                if bitmap[row * 5 + col] == "1":
                    yy, xx = y + row, x + col
                    if 0 <= yy < len(pixels) and 0 <= xx < len(pixels[0]):
                        pixels[yy][xx] = value
        x += 6


def contact_sheet(path, tiles, columns=4, label_height=10):
    """tiles: [(label, pixels)] same-size greyscale tiles -> one labelled PNG."""
    if not tiles:
        raise ValueError("No tiles for contact sheet")
    tile_h, tile_w = len(tiles[0][1]), len(tiles[0][1][0])
    rows = (len(tiles) + columns - 1) // columns
    sheet = [[18] * (columns * tile_w) for _ in range(rows * (tile_h + label_height))]
    for index, (label, pixels) in enumerate(tiles):
        ox = (index % columns) * tile_w
        oy = (index // columns) * (tile_h + label_height)
        for y in range(tile_h):
            sheet[oy + label_height + y][ox:ox + tile_w] = pixels[y]
        draw_text(sheet, ox + 2, oy + 2, label[: tile_w // 6])
    return write_png(path, sheet)
