"""Render ONLY the views listed in a contact-sheet request and tile them into one PNG (Cycles CPU, low samples).

  blender --background --factory-startup --python-exit-code 1 --python contact_sheet.py -- \
      --rig rig.blend --request gates/contact-sheet-request.json --output gates/contact-sheet.png
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _forge_common as fc  # noqa: E402
from pose_render import apply_pose  # noqa: E402  (pose_render's main() only runs when it is the script)

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector  # noqa: E402

VIEW_OFFSETS = {"front": (0, -4, 0.1), "side": (4, 0, 0.1), "three_quarter": (2.8, -2.8, 0.1), "back": (0, 4, 0.1)}
TILE = 256


def configure(p):
    p.add_argument("--rig", required=True)
    p.add_argument("--request", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--poses", help="stress-poses.json (defaults to the request's pose views being skipped)")
    p.add_argument("--samples", type=int, default=6)
    p.add_argument("--max-tiles", type=int, default=16)


def main():
    args = fc.parse(__doc__, configure)
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    poses = json.loads(Path(args.poses).read_text(encoding="utf-8"))["poses"] if args.poses else {}
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.rig).resolve()))
    rig = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    rig.animation_data_clear()
    scene = bpy.context.scene
    lo, hi = fc.bounds(fc.mesh_objects())
    h = hi[2] - lo[2]
    fc.neutral_cycles(scene, samples=args.samples, resolution=(TILE, TILE))
    fc.add_lights(scene, h)
    camera = fc.ortho_camera(scene)
    tiles = []
    seen = set()
    with tempfile.TemporaryDirectory() as tmp:
        for view in request["views"]:
            key = (view["name"], view["kind"], view.get("pose"))
            if key in seen or view["kind"] not in ("static", "pose") or len(tiles) >= args.max_tiles:
                continue
            seen.add(key)
            if view["kind"] == "pose":
                if view.get("pose") not in poses:
                    continue
                apply_pose(rig, poses[view["pose"]])
            else:
                apply_pose(rig, [])
            offset = VIEW_OFFSETS.get(view["name"], VIEW_OFFSETS["front"])
            if view.get("focus") in ("Head",):
                fc.aim(camera, rig.matrix_world @ rig.pose.bones["Head"].head + Vector((0, 0, 0.06 * h)), (0, -3, 0), h * 0.32)
            elif view.get("focus") in ("Hands", "LeftHand"):
                fc.aim(camera, rig.matrix_world @ rig.pose.bones["LeftHand"].head, (0, -2, 0.15), h * 0.24)
            else:
                fc.aim(camera, (0, 0, h * 0.52), offset, h * 1.25)
            target = Path(tmp) / ("%02d.png" % len(tiles))
            scene.render.filepath = str(target)
            bpy.ops.render.render(write_still=True)
            image = bpy.data.images.load(str(target))
            pixels = np.array(image.pixels[:], dtype=np.float32).reshape(TILE, TILE, 4)
            tiles.append(pixels)
            bpy.data.images.remove(image)
    if not tiles:
        raise SystemExit("no static/pose views to render in the request")
    columns = 4
    rows = (len(tiles) + columns - 1) // columns
    sheet = np.zeros((rows * TILE, columns * TILE, 4), dtype=np.float32)
    sheet[..., 3] = 1.0
    for i, tile in enumerate(tiles):
        r, c = divmod(i, columns)
        # Blender image rows start at the bottom.
        sheet[(rows - 1 - r) * TILE:(rows - r) * TILE, c * TILE:(c + 1) * TILE] = tile
    out = bpy.data.images.new("ForgeContactSheet", columns * TILE, rows * TILE, alpha=True)
    out.pixels.foreach_set(sheet.ravel())
    out.filepath_raw = str(Path(args.output).resolve())
    out.file_format = "PNG"
    out.save()
    print("FORGE_CONTACT_SHEET", len(tiles), flush=True)


if __name__ == "__main__":
    main()
