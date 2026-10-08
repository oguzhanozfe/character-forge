"""Render the stress-pose review views on the real rig (Cycles CPU, low samples: never competes for the GPU).
Pose operations come from stress-poses.json written by character-forge, so Python and Blender share one definition.

  blender --background --factory-startup --python-exit-code 1 --python pose_render.py -- \
      --rig rig.blend --poses stress-poses.json --output-dir <run>/renders --height 1.78 [--samples 8]
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _forge_common as fc  # noqa: E402

import bpy  # noqa: E402
from mathutils import Quaternion, Vector  # noqa: E402

HAND_POSES = {"fist", "claw", "twist", "wrist"}


def configure(p):
    p.add_argument("--rig", required=True)
    p.add_argument("--poses", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--height", type=float, required=True)
    p.add_argument("--samples", type=int, default=8)
    p.add_argument("--only", nargs="*", help="pose names (default: the file's render list)")


def apply_pose(rig, ops):
    for pb in rig.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = Quaternion()
        pb.location = (0, 0, 0)
    for op in ops:
        pb = rig.pose.bones.get(op["bone"])
        if pb is None:
            if op.get("optional"):
                continue
            raise SystemExit("rig lacks bone " + op["bone"])
        if "translate" in op:
            pb.location = Vector(pb.location) + Vector(op["translate"])
            continue
        axis = Vector(op["axis"])
        if op["frame"] == "world":
            axis = pb.bone.matrix_local.to_3x3().transposed() @ axis
        pb.rotation_quaternion = Quaternion(axis.normalized(), math.radians(op["deg"])) @ pb.rotation_quaternion
    bpy.context.view_layer.update()


def main():
    args = fc.parse(__doc__, configure)
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    spec = json.loads(Path(args.poses).read_text(encoding="utf-8"))
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.rig).resolve()))
    rig = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    rig.animation_data_clear()
    scene = bpy.context.scene
    for obj in list(scene.objects):
        if obj.type in ("LIGHT", "CAMERA"):
            bpy.data.objects.remove(obj, do_unlink=True)
    fc.neutral_cycles(scene, samples=args.samples, resolution=(384, 512))
    fc.add_lights(scene, args.height)
    camera = fc.ortho_camera(scene)
    h = args.height
    rows = []
    for name in args.only or spec["renders"]:
        apply_pose(rig, spec["poses"][name])
        if name in HAND_POSES:
            target = rig.matrix_world @ rig.pose.bones["LeftHand"].head
            fc.aim(camera, target, (0, -2, 0.15), h * 0.24)
        else:
            fc.aim(camera, (0, 0, h * 0.52), (0, -4, 0.1), h * 1.25)
        scene.render.filepath = str(out / (name + ".png"))
        bpy.ops.render.render(write_still=True)
        rows.append({"pose": name, "image": name + ".png",
                     "bone_heads": {pb.name: list(rig.matrix_world @ pb.head) for pb in rig.pose.bones}})
    fc.write_json(out / "index.json", {"renders": rows, "engine": "CYCLES CPU", "samples": args.samples})
    print("FORGE_POSE_RENDER_DONE", len(rows), flush=True)


if __name__ == "__main__":
    main()
