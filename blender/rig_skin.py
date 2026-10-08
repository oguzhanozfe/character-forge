"""Rig and skin: build the contract armature from skeleton.json (head/tail/roll), bind the low mesh with automatic
(bone heat) weights, fall back to nearest-bone weights for anything bone heat missed, limit to N influences,
normalize, export bind.fbx and verify an FBX round trip.

  blender --background --factory-startup --python-exit-code 1 --python rig_skin.py -- \
      --mesh low.blend --skeleton skeleton.json --output-dir <run> --id demo [--max-influences 4]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _forge_common as fc  # noqa: E402

import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402
from mathutils.geometry import intersect_point_line  # noqa: E402
from mathutils.kdtree import KDTree  # noqa: E402


def configure(p):
    p.add_argument("--mesh", required=True)
    p.add_argument("--skeleton", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--max-influences", type=int, default=4)


def build_armature(skeleton, name):
    data = bpy.data.armatures.new(name + "_Armature")
    rig = bpy.data.objects.new(name + "_Rig", data)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for b in skeleton["bones"]:
        bone = data.edit_bones.new(b["name"])
        bone.head = Vector(b["head"])
        bone.tail = Vector(b["tail"])
        m = b["matrix"]
        bone.align_roll(Vector((m[0][2], m[1][2], m[2][2])))
        bone.use_deform = bool(b.get("deform", True))
    for b in skeleton["bones"]:
        if b["parent"]:
            data.edit_bones[b["name"]].parent = data.edit_bones[b["parent"]]
            data.edit_bones[b["name"]].use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in rig.pose.bones:
        pb.rotation_mode = "QUATERNION"
    return rig


def nearest_bone_weights(obj, rig, vertex_ids):
    segments = [(b.name, b.head_local, b.tail_local) for b in rig.data.bones if b.use_deform]
    for vi in vertex_ids:
        co = obj.data.vertices[vi].co
        scored = []
        for name, a, b in segments:
            point, t = intersect_point_line(co, a, b)
            t = max(0.0, min(1.0, t))
            scored.append(((co - (a + (b - a) * t)).length, name))
        scored.sort()
        kept = [(n, 1.0 / (d + 0.004) ** 4) for d, n in scored[:4] if d <= scored[0][0] * 1.8 + 0.01]
        total = sum(w for _, w in kept)
        for n, w in kept:
            group = obj.vertex_groups.get(n) or obj.vertex_groups.new(name=n)
            group.add([vi], w / total, "REPLACE")


def tpose_bind(rig, body):
    """Re-bind in T-pose for a clean Unity Humanoid Avatar (port of BBFPS export_humanoid_bind): pose the arm chains
    straight along +/-X, bake that deformation into the mesh, commit the pose as the new rest and re-bind."""
    bpy.context.view_layer.objects.active = rig
    for side, sign in (("Left", 1.0), ("Right", -1.0)):
        for suffix in ("UpperArm", "LowerArm", "Hand"):
            pb = rig.pose.bones.get(side + suffix)
            if pb is None:
                continue
            bpy.context.view_layer.update()
            m = pb.matrix.copy()
            delta = (pb.tail - pb.head).normalized().rotation_difference(Vector((sign, 0.0, 0.0)))
            pb.matrix = Matrix.LocRotScale(m.translation, delta @ m.to_quaternion(), Vector((1.0, 1.0, 1.0)))
            bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph).to_mesh()
    posed = [v.co.copy() for v in evaluated.vertices]
    body.evaluated_get(depsgraph).to_mesh_clear()
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    modifier = next(m for m in body.modifiers if m.type == "ARMATURE")
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    modifier = body.modifiers.new("Armature", "ARMATURE")
    modifier.object = rig
    modifier.use_deform_preserve_volume = False
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph).to_mesh()
    drift = max(((a.co - b).length for a, b in zip(evaluated.vertices, posed)), default=0.0)
    body.evaluated_get(depsgraph).to_mesh_clear()
    return drift


def main():
    args = fc.parse(__doc__, configure)
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    skeleton = json.loads(Path(args.skeleton).read_text(encoding="utf-8"))
    fc.reset()
    fc.import_any(args.mesh)
    for obj in list(bpy.context.scene.objects):
        if obj.type not in ("MESH",):
            bpy.data.objects.remove(obj, do_unlink=True)
    meshes = fc.mesh_objects()
    fc.bake_transforms(meshes)
    body = fc.join(meshes, args.id + "_Body") if len(meshes) > 1 else meshes[0]
    body.name = args.id + "_Body"
    body.vertex_groups.clear()
    rig = build_armature(skeleton, args.id)
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    heat_ok = True
    try:
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    except RuntimeError as error:
        heat_ok = False
        print("bone heat failed:", error, flush=True)
        bpy.ops.object.parent_set(type="ARMATURE_NAME")
    names = {g.index: g.name for g in body.vertex_groups}
    unweighted = [v.index for v in body.data.vertices if not any(g.weight > 1e-6 for g in v.groups)]
    if unweighted:
        nearest_bone_weights(body, rig, unweighted)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.ops.object.vertex_group_clean(group_select_mode="ALL", limit=1e-4)
    bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=args.max_influences)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
    modifier = next(m for m in body.modifiers if m.type == "ARMATURE")
    modifier.use_deform_preserve_volume = False
    names = {g.index: g.name for g in body.vertex_groups}
    weights = [[[names[g.group], round(g.weight, 6)] for g in sorted(v.groups, key=lambda g: -g.weight) if g.weight > 1e-6]
               for v in body.data.vertices]
    fc.write_json(out / "skin.json", {"format": "character-forge/skin@1", "vertex_count": len(weights), "weights": weights})
    fc.write_obj([body], out / "rigged.obj", header="rigged %s (vertex order matches skin.json)" % args.id)
    exported = {"format": "character-forge/skeleton@1", "bones": [], "landmarks": skeleton.get("landmarks", {})}
    matrix_difference = 0.0
    source = {b["name"]: b for b in skeleton["bones"]}
    for bone in rig.data.bones:
        m = bone.matrix_local
        exported["bones"].append({"name": bone.name, "parent": bone.parent.name if bone.parent else None,
                                  "head": list(bone.head_local), "tail": list(bone.tail_local),
                                  "matrix": [list(row) for row in m], "deform": bone.use_deform})
        ref = source[bone.name]["matrix"]
        matrix_difference = max(matrix_difference, max(abs(m[i][j] - ref[i][j]) for i in range(4) for j in range(4)))
    fc.write_json(out / "skeleton-blender.json", exported)
    # Bind drift: evaluated rest-pose skin must equal the bind mesh.
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph).to_mesh()
    bind_drift = max(((a.co - b.co).length for a, b in zip(evaluated.vertices, body.data.vertices)), default=0.0)
    body.evaluated_get(depsgraph).to_mesh_clear()
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "rig.blend"))
    # rig.blend keeps the A-pose rest used by the screens and motion export; the FBX carries a T-pose bind.
    tpose_drift = tpose_bind(rig, body)
    original_points = [body.matrix_world @ v.co for v in body.data.vertices]
    original_bones = {b.name: rig.matrix_world @ b.head_local for b in rig.data.bones}
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.export_scene.fbx(filepath=str(out / "bind.fbx"), use_selection=True, object_types={"MESH", "ARMATURE"},
                             axis_forward="-Z", axis_up="Y", add_leaf_bones=False, bake_anim=False, path_mode="STRIP",
                             use_armature_deform_only=False, mesh_smooth_type="FACE")
    # Round trip: re-import the FBX into an empty scene and compare world-space bones and bind vertices.
    fc.reset()
    bpy.ops.import_scene.fbx(filepath=str(out / "bind.fbx"))
    imported_rig = next((o for o in bpy.context.scene.objects if o.type == "ARMATURE"), None)
    imported_meshes = fc.mesh_objects()
    bpy.context.view_layer.update()
    missing = sorted(set(original_bones) - set(imported_rig.data.bones.keys())) if imported_rig else sorted(original_bones)
    bone_drift = max(((imported_rig.matrix_world @ imported_rig.data.bones[n].head_local) - p).length
                     for n, p in original_bones.items() if imported_rig and n in imported_rig.data.bones) if imported_rig else 1.0
    tree = KDTree(len(original_points))
    for i, p in enumerate(original_points):
        tree.insert(p, i)
    tree.balance()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    vertex_drift = 0.0
    imported_vertices = 0
    for obj in imported_meshes:
        mesh = obj.evaluated_get(depsgraph).to_mesh()
        for v in mesh.vertices:
            _, _, distance = tree.find(obj.matrix_world @ v.co)
            vertex_drift = max(vertex_drift, distance)
            imported_vertices += 1
        obj.evaluated_get(depsgraph).to_mesh_clear()
    report = {"mode": "real", "method": "FBX export + re-import into an empty scene", "blender": bpy.app.version_string,
              "bone_heat_succeeded": heat_ok, "bind_pose": "T-pose (arms along +/-X)", "tpose_rebind_drift_m": tpose_drift, "nearest_bone_fallback_vertices": len(unweighted),
              "max_bind_vertex_drift_m": max(vertex_drift, bind_drift, tpose_drift), "evaluated_rest_drift_m": bind_drift,
              "max_bone_head_drift_m": bone_drift, "missing_bones_after_import": missing,
              "original_vertices": len(original_points), "imported_vertices": imported_vertices,
              "skeleton_matrix_max_difference": matrix_difference}
    fc.write_json(out / "roundtrip.json", report)
    print("FORGE_RIG_DONE", json.dumps({k: report[k] for k in ("bone_heat_succeeded", "max_bind_vertex_drift_m", "max_bone_head_drift_m")}), flush=True)


if __name__ == "__main__":
    main()
