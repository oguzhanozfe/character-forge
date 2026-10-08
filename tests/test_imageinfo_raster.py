"""Image header parsing and the stdlib PNG writer."""
import struct
import zlib

import pytest

from character_forge.imageinfo import image_info
from character_forge.meshkit import raster
from character_forge.util import ForgeError


def test_png_writer_grey_rgb_rgba(tmp_path):
    for name, pixels, rgb, expect_alpha in (("g.png", [[10, 20], [30, 40]], False, False),
                                            ("c.png", [[(1, 2, 3)] * 3] * 2, True, False),
                                            ("a.png", [[(1, 2, 3, 4)] * 2] * 2, True, True)):
        path = raster.write_png(tmp_path / name, pixels, rgb=rgb)
        info = image_info(path)
        assert info["format"] == "png" and info["width"] == len(pixels[0]) and info["height"] == len(pixels)
        assert info["alpha"] is expect_alpha
        data = path.read_bytes()
        idat = data[data.index(b"IDAT") + 4: data.index(b"IEND") - 8]
        assert len(zlib.decompress(idat)) == len(pixels) * (1 + len(pixels[0]) * (len(pixels[0][0]) if rgb else 1))


def test_jpeg_and_webp_headers(tmp_path):
    jpeg = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 4) + b"\x00\x00" + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 600, 800) + b"\x00" * 20
    (tmp_path / "a.jpg").write_bytes(jpeg)
    assert image_info(tmp_path / "a.jpg") == {"format": "jpeg", "width": 800, "height": 600, "alpha": False}
    webp = b"RIFF" + b"\x00" * 4 + b"WEBPVP8X" + b"\x00" * 4 + b"\x10\x00\x00\x00" + (1023).to_bytes(3, "little") + (511).to_bytes(3, "little")
    (tmp_path / "a.webp").write_bytes(webp)
    info = image_info(tmp_path / "a.webp")
    assert (info["width"], info["height"], info["alpha"]) == (1024, 512, True)
    (tmp_path / "x.gif").write_bytes(b"GIF89a")
    with pytest.raises(ForgeError):
        image_info(tmp_path / "x.gif")


def test_contact_sheet_labels_and_layout(tmp_path):
    tiles = [("FRONT", [[100] * 20 for _ in range(20)]), ("SIDE", [[200] * 20 for _ in range(20)]), ("X", [[0] * 20 for _ in range(20)])]
    path = raster.contact_sheet(tmp_path / "s.png", tiles, columns=2, label_height=10)
    info = image_info(path)
    assert (info["width"], info["height"]) == (40, 60)


def test_zoom_window_renders_a_close_up():
    from character_forge.meshkit.synth import synthetic_humanoid
    mesh, lm = synthetic_humanoid(seed=1)
    tris = [t for _, t, _ in mesh.triangles()]
    _, _, _, full = raster.render(mesh.vertices, tris, "front", 64, shade=False)
    head = lm["Head"]
    _, _, _, close = raster.render(mesh.vertices, tris, "front", 64, shade=False, window=(head[0], head[2], 0.4))
    assert sum(map(sum, close)) > sum(map(sum, full))      # the face fills more of the frame
