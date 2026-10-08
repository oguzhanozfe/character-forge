"""Skin weights, linear blend skinning and the 13 controlled stress poses.

The linear blend skinning here matches Blender's Armature modifier without preserve-volume and Unity's
four-bone skinning, so measurements on interchange data describe what the exported FBX will do.
"""
from __future__ import annotations

import math

from . import vecmath as vm
from .skeleton import SIDES, Skeleton

SKIN_FORMAT = "character-forge/skin@1"


def skin_to_json(weights):
    return {"format": SKIN_FORMAT, "vertex_count": len(weights),
            "weights": [[[name, round(w, 6)] for name, w in row] for row in weights]}


def skin_from_json(value):
    if value.get("format") != SKIN_FORMAT:
        raise ValueError("Not a character-forge skin file")
    rows = [[(str(name), float(w)) for name, w in row] for row in value["weights"]]
    if len(rows) != value["vertex_count"]:
        raise ValueError("Skin vertex count mismatch")
    return rows


def limit_and_normalize(row, limit=4):
    row = sorted(((n, w) for n, w in row if w > 1e-6), key=lambda item: -item[1])[:limit]
    total = sum(w for _, w in row)
    return [(n, w / total) for n, w in row] if total > 0 else []


def validate_weights(weights, skeleton: Skeleton, vertex_count: int, max_influences=4):
    deform = {b.name for b in skeleton.bones.values() if b.deform}
    unweighted = nonfinite = over_limit = 0
    worst_sum_error = 0.0
    unknown = set()
    for row in weights:
        if not row:
            unweighted += 1
            continue
        if len(row) > max_influences:
            over_limit += 1
        total = 0.0
        for name, w in row:
            if not math.isfinite(w) or w < 0:
                nonfinite += 1
            if name not in deform:
                unknown.add(name)
            total += w
        worst_sum_error = max(worst_sum_error, abs(total - 1.0))
    return {"vertex_count_matches": len(weights) == vertex_count, "unweighted_vertices": unweighted,
            "nonfinite_or_negative_weights": nonfinite, "vertices_over_influence_limit": over_limit,
            "max_weight_sum_error": worst_sum_error, "unknown_or_non_deform_bones": sorted(unknown),
            "max_influences": max((len(r) for r in weights), default=0)}


# ---------------------------------------------------------------- posing

def rest_local(skeleton: Skeleton, name):
    bone = skeleton.bones[name]
    if bone.parent is None:
        return bone.matrix
    return vm.mat_mul(vm.mat_rigid_inverse(skeleton.bones[bone.parent].matrix), bone.matrix)


def posed_world(skeleton: Skeleton, basis):
    """basis: {bone: (quat, translation)} in the bone's local rest frame (Blender pose_bone.matrix_basis)."""
    world = {}
    for name, bone in skeleton.bones.items():
        q, t = basis.get(name, (vm.quat_identity(), (0.0, 0.0, 0.0)))
        b = vm.mat_from_rot_trans(vm.quat_to_mat3(q), t)
        local = vm.mat_mul(rest_local(skeleton, name), b)
        world[name] = vm.mat_mul(world[bone.parent], local) if bone.parent else local
    return world


def skin_matrices(skeleton: Skeleton, basis):
    world = posed_world(skeleton, basis)
    return {name: vm.mat_mul(world[name], vm.mat_rigid_inverse(skeleton.bones[name].matrix)) for name in world}


def deform(vertices, weights, matrices):
    out = []
    for v, row in zip(vertices, weights):
        if not row:
            out.append(v)
            continue
        x = y = z = 0.0
        for name, w in row:
            px, py, pz = vm.mat_apply(matrices[name], v)
            x += w * px
            y += w * py
            z += w * pz
        out.append((x, y, z))
    return out


# ---------------------------------------------------------------- the 13 stress poses

STRESS_POSES = ["rest", "elbow45", "elbow90", "elbow135", "claw", "fist", "twist", "wrist",
                "reach", "raise", "crouch", "crossbody", "headturn"]
# Poses rendered for review in the contact sheet (hands get close-ups).
STRESS_RENDERS = ["elbow135", "fist", "claw", "twist", "wrist", "crouch", "crossbody", "headturn"]


def stress_pose_ops(name, height=1.78):
    """Declarative operations for one stress pose. Each op pre-multiplies the bone's local rotation.

    frame='local': axis in the bone's rest frame (X is the hinge: +X flexes elbows/fingers forward, legs forward).
    frame='world': axis in armature space, converted into the bone's rest frame.
    """
    if name not in STRESS_POSES:
        raise KeyError(name)
    ops = []
    for side, sgn in (("Left", 1.0), ("Right", -1.0)):
        elbow = {"elbow45": 45, "elbow90": 90, "elbow135": 135, "claw": 45, "fist": 45, "twist": 45,
                 "wrist": 45, "reach": 30, "crossbody": 80}.get(name)
        if elbow:
            ops.append({"bone": side + "LowerArm", "frame": "local", "axis": [1, 0, 0], "deg": elbow})
        if name in ("claw", "fist"):
            for finger in ("Thumb", "Index", "Middle", "Ring", "Little"):
                angles = (80, 100, 70) if name == "fist" else (20, 50, 35)
                for segment, angle in zip(("Proximal", "Intermediate", "Distal"), angles):
                    ops.append({"bone": side + finger + segment, "frame": "local", "axis": [1, 0, 0],
                                "deg": angle * (0.65 if finger == "Thumb" else 1.0)})
        if name == "twist":
            ops.append({"bone": side + "Hand", "frame": "local", "axis": [0, 1, 0], "deg": sgn * 85})
            ops.append({"bone": side + "ForearmTwist", "frame": "local", "axis": [0, 1, 0], "deg": sgn * 42.5, "optional": True})
        if name == "wrist":
            ops.append({"bone": side + "Hand", "frame": "local", "axis": [1, 0, 0], "deg": 55})
        if name == "reach":
            ops.append({"bone": side + "UpperArm", "frame": "world", "axis": [1, 0, 0], "deg": -75})
        if name == "crossbody":
            ops.append({"bone": side + "UpperArm", "frame": "world", "axis": [1, 0, 0], "deg": -60})
            ops.append({"bone": side + "UpperArm", "frame": "world", "axis": [0, 0, 1], "deg": -sgn * 45})
        if name == "raise":
            ops.append({"bone": side + "UpperArm", "frame": "world", "axis": [0, 1, 0], "deg": -sgn * 95})
        if name == "crouch":
            ops.append({"bone": side + "UpperLeg", "frame": "local", "axis": [1, 0, 0], "deg": 65})
            ops.append({"bone": side + "LowerLeg", "frame": "local", "axis": [1, 0, 0], "deg": -110})
            ops.append({"bone": side + "Foot", "frame": "local", "axis": [1, 0, 0], "deg": 45})
    if name == "crouch":
        ops.append({"bone": "Hips", "translate": [0, -0.15 * height, 0]})
    if name == "headturn":
        ops.append({"bone": "Neck", "frame": "local", "axis": [0, 1, 0], "deg": 35})
        ops.append({"bone": "Head", "frame": "local", "axis": [0, 1, 0], "deg": 20})
    return ops


def ops_to_basis(skeleton: Skeleton, ops):
    basis = {}
    for op in ops:
        bone = skeleton.bones.get(op["bone"])
        if bone is None:
            if op.get("optional"):
                continue
            raise KeyError("Stress pose needs bone " + op["bone"])
        q, t = basis.get(bone.name, (vm.quat_identity(), (0.0, 0.0, 0.0)))
        if "translate" in op:
            t = vm.add(t, tuple(op["translate"]))
        else:
            axis = tuple(op["axis"])
            if op["frame"] == "world":
                axis = vm.mat3_apply(vm.mat3_transpose(vm.mat_rot3(bone.matrix)), axis)
            q = vm.quat_mul(vm.quat_axis_angle(axis, op["deg"]), q)
        basis[bone.name] = (q, t)
    return basis


def stress_poses_json(height=1.78):
    """Single source of truth exported for blender/pose_screen.py."""
    return {"format": "character-forge/stress-poses@1", "poses": {n: stress_pose_ops(n, height) for n in STRESS_POSES},
            "renders": STRESS_RENDERS}


def side_of(name):
    for side in SIDES:
        if name.startswith(side):
            return side
    return None
