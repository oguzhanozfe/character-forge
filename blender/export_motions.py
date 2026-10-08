"""Write retargeted motions (baked local rotations from character-forge) onto the rig and export one FBX per clip
named <id>@<clip>.fbx (Unity's animation naming), armature only, ready for Humanoid import with the character's Avatar.

  blender --background --factory-startup --python-exit-code 1 --python export_motions.py -- \
      --rig rig.blend --baked-dir <run>/baked --output-dir <run>/Motions --id demo
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _forge_common as fc  # noqa: E402

import bpy  # noqa: E402
from mathutils import Quaternion, Vector  # noqa: E402


def configure(p):
    p.add_argument("--rig", required=True)
    p.add_argument("--baked-dir", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--id", required=True)


def main():
    args = fc.parse(__doc__, configure)
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.rig).resolve()))
    rig = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    scene = bpy.context.scene
    written, probes = [], {}
    for path in sorted(Path(args.baked_dir).glob("*.baked.json")):
        baked = json.loads(path.read_text(encoding="utf-8"))
        rig.animation_data_clear()
        for a in list(bpy.data.actions):
            bpy.data.actions.remove(a)
        action = bpy.data.actions.new("%s_%s" % (args.id, baked["id"]))
        rig.animation_data_create()
        rig.animation_data.action = action
        scene.render.fps = int(baked["fps"])
        frames = baked["frames"]
        for f in range(frames):
            for name, track in baked["bones"].items():
                pb = rig.pose.bones.get(name)
                if pb is None:
                    continue
                pb.rotation_mode = "QUATERNION"
                pb.rotation_quaternion = Quaternion(track[f])
                pb.keyframe_insert("rotation_quaternion", frame=f + 1, group=name)
                if name == "Hips":
                    pb.location = Vector(baked["hips_location"][f])
                    pb.keyframe_insert("location", frame=f + 1, group=name)
        scene.frame_start, scene.frame_end = 1, frames
        # Probe: Blender's own evaluation of the keyed pose, compared by character-forge with its Python skinning.
        probe_frame = frames // 2
        scene.frame_set(probe_frame + 1)
        bpy.context.view_layer.update()
        probes[baked["id"]] = {"frame": probe_frame, "bone_heads": {pb.name: list(rig.matrix_world @ pb.head) for pb in rig.pose.bones}}
        bpy.ops.object.select_all(action="DESELECT")
        rig.select_set(True)
        bpy.context.view_layer.objects.active = rig
        target = out / ("%s@%s.fbx" % (args.id, baked["id"]))
        bpy.ops.export_scene.fbx(filepath=str(target), use_selection=True, object_types={"ARMATURE"}, axis_forward="-Z", axis_up="Y",
                                 add_leaf_bones=False, use_armature_deform_only=False, bake_anim=True,
                                 bake_anim_use_all_actions=False, bake_anim_use_nla_strips=False, bake_anim_simplify_factor=0.0)
        written.append(target.name)
        print("FORGE_MOTION_EXPORTED", target.name, frames, flush=True)
    fc.write_json(out / "export-index.json", {"clips": written, "probes": probes})


if __name__ == "__main__":
    main()
