"""Stage 5 - rig: contract skeleton fitted to landmarks, skin weights, round trip, hitboxes and gore regions."""
from __future__ import annotations

from ..adapters import blender
from ..meshkit import analysis
from ..meshkit import vecmath as vm
from ..meshkit.obj import read_obj, write_obj
from ..meshkit.skeleton import FINGER_BONES, FINGERS, Skeleton, build_skeleton
from ..meshkit.skinning import skin_from_json, skin_to_json, validate_weights
from ..meshkit.synth import synthetic_weights
from ..meshkit.util_stats import percentile
from ..presets import required_bones
from ..util import read_json, write_json
from .base import Stage


def hitboxes(skeleton: Skeleton, vertices, weights, regions):
    """Capsule per hit region from vertices dominated by the region's bones."""
    owner = {}
    for region, spec in regions.items():
        bones = [b for b in spec["bones"] if b in skeleton.bones]
        if spec.get("include_fingers"):
            side = "Left" if region.startswith("Left") else "Right"
            bones += [b for b in FINGER_BONES if b.startswith(side) and b in skeleton.bones]
        for b in bones:
            owner.setdefault(b, []).append(region)
    samples = {r: [] for r in regions}
    for v, row in zip(vertices, weights):
        if not row:
            continue
        dominant = max(row, key=lambda item: item[1])[0]
        for region in owner.get(dominant, []):
            spec = regions[region]
            primary = skeleton.bones[spec["bones"][0]] if spec["bones"][0] in skeleton.bones else skeleton.bones[dominant]
            side = spec.get("side")
            if side:
                # Front = toward -Y (the character faces -Y). Split by the bone's Y.
                in_front = v[1] < primary.head[1]
                if (side == "front") != in_front:
                    continue
            samples[region].append(v)
    result = []
    for region, spec in regions.items():
        bone = skeleton.bones.get(spec["bones"][0])
        pts = samples[region]
        if bone is None:
            result.append({"region": region, "bone": spec["bones"][0], "vertices": 0, "radius_m": 0.0})
            continue
        distances = [vm.point_segment_distance(p, bone.head, bone.tail)[0] for p in pts]
        result.append({"region": region, "bone": bone.name, "side": spec.get("side"), "vertices": len(pts),
                       "radius_m": round(percentile(distances, 75), 4) if pts else 0.0, "length_m": round(bone.length, 4)})
    return result


def gore_regions(skeleton: Skeleton, mesh, weights, gore):
    """Triangles dominated (>= 50 % summed weight) by each part's bone subtree: the future gib mesh."""
    rows = []
    for part, bone_name in gore.items():
        if bone_name not in skeleton.bones:
            rows.append({"part": part, "bone": bone_name, "triangles": 0})
            continue
        subtree = {bone_name, *skeleton.descendants(bone_name)}
        share = [sum(w for n, w in row if n in subtree) for row in weights]
        count = sum(1 for _, (a, b, c), _ in mesh.triangles() if (share[a] + share[b] + share[c]) / 3 >= 0.5)
        rows.append({"part": part, "bone": bone_name, "triangles": count, "subtree_bones": len(subtree)})
    return rows


class RigStage(Stage):
    name = "rig"
    title = "Rig and skin"
    needs = ("preflight", "lowmesh")
    adapter = "blender"
    tool_files = ("blender/rig_skin.py", "blender/_forge_common.py")

    def params(self, ws, character, preset, machine):
        return {"required_bones": required_bones(preset), "hit_regions": preset.get("hit_regions", {}),
                "gore_regions": preset.get("gore_regions", {}), "max_influences": preset["thresholds"].get("max_influences", 4)}

    def run(self, ctx):
        landmarks = {k: tuple(v) for k, v in read_json(ctx.inputs["preflight.landmarks"])["landmarks"].items()}
        skeleton = build_skeleton(landmarks)
        skeleton_path = write_json(ctx.out("skeleton.json"), skeleton.to_json())
        outputs = {"skeleton": skeleton_path}
        if ctx.mode == "fake":
            mesh = read_obj(ctx.inputs["lowmesh.low"])
            weights = synthetic_weights(mesh, skeleton, limit=ctx.params["max_influences"])
            write_obj(mesh, ctx.out("rigged.obj"), header="rigged mesh (vertex order matches skin.json)")
            write_json(ctx.out("skin.json"), skin_to_json(weights))
            # JSON round trip stands in for the FBX re-import in fake mode.
            again = Skeleton.from_json(read_json(skeleton_path))
            drift = max(vm.distance(a.head, b.head) for a, b in zip(skeleton.bones.values(), again.bones.values()))
            write_json(ctx.out("roundtrip.json"), {"mode": "fake", "method": "skeleton JSON round trip",
                                                   "max_bone_head_drift_m": drift, "max_bind_vertex_drift_m": 0.0,
                                                   "skeleton_matrix_max_difference": 0.0})
        else:
            blender.run(ctx.machine, "rig_skin.py", ["--mesh", ctx.inputs.get("lowmesh.blend", ctx.inputs["lowmesh.low"]),
                                                     "--skeleton", skeleton_path, "--output-dir", ctx.run_dir, "--id", ctx.ws.id,
                                                     "--max-influences", ctx.params["max_influences"]],
                        ctx.out("logs/rig.log"), expect=[ctx.run_dir / n for n in ("rig.blend", "bind.fbx", "skin.json", "rigged.obj", "roundtrip.json")],
                        plan=ctx.plan, mode=ctx.mode)
            outputs.update(blend=ctx.run_dir / "rig.blend", fbx=ctx.run_dir / "bind.fbx")
        outputs.update(rigged=ctx.run_dir / "rigged.obj", skin=ctx.run_dir / "skin.json", roundtrip=ctx.run_dir / "roundtrip.json")
        mesh = read_obj(outputs["rigged"])
        weights = skin_from_json(read_json(outputs["skin"]))
        neighbours = analysis.adjacency(mesh, analysis.weld_map(mesh.vertices))
        digits = {}
        for side in ("Left", "Right"):
            digits[side] = analysis.digit_separation(mesh.vertices, neighbours, landmarks[side + "Hand"], landmarks[side + "MiddleTip"])
        report = {"weights": validate_weights(weights, skeleton, len(mesh.vertices), ctx.params["max_influences"]),
                  "bones": len(skeleton.bones), "finger_bones": sum(1 for b in skeleton.bones if any(f in b for f in FINGERS)),
                  "missing_required_bones": [b for b in ctx.params["required_bones"] if b not in skeleton.bones],
                  "digits": digits, "roundtrip": read_json(outputs["roundtrip"])}
        outputs["hitboxes"] = write_json(ctx.out("hitboxes.json"), {"hitboxes": hitboxes(skeleton, mesh.vertices, weights, ctx.params["hit_regions"])})
        outputs["gore"] = write_json(ctx.out("gore.json"), {"gore": gore_regions(skeleton, mesh, weights, ctx.params["gore_regions"])})
        outputs["analysis"] = write_json(ctx.out("analysis.json"), report)
        return outputs

    def gate(self, ctx, outputs):
        g = ctx.gate()
        th = ctx.thresholds
        r = read_json(outputs["analysis"])
        w = r["weights"]
        g.metrics.update(weights=w, bones=r["bones"], finger_bones=r["finger_bones"], digits=r["digits"])
        g.check("required_bones", not r["missing_required_bones"], r["missing_required_bones"], [], "Missing contract bones.")
        if ctx.preset.get("require_fingers"):
            g.check("finger_bones", r["finger_bones"] == 30, r["finger_bones"], 30, "Need 3 bones x 5 digits x 2 hands.")
        g.check("vertex_count_matches", w["vertex_count_matches"], None, None, "skin.json does not match the mesh.")
        g.check("no_unweighted_vertices", w["unweighted_vertices"] == 0, w["unweighted_vertices"], 0, "Unweighted vertices.")
        g.check("finite_weights", w["nonfinite_or_negative_weights"] == 0, w["nonfinite_or_negative_weights"], 0, "Bad weights.")
        g.check("max_influences", w["max_influences"] <= th.get("max_influences", 4), w["max_influences"], th.get("max_influences", 4),
                "More influences than the runtime supports.")
        g.check("normalized", w["max_weight_sum_error"] <= th.get("weight_sum_tolerance", 1e-4), w["max_weight_sum_error"],
                th.get("weight_sum_tolerance", 1e-4), "Weights not normalized.")
        g.check("deform_bones_only", not w["unknown_or_non_deform_bones"], w["unknown_or_non_deform_bones"], [], "Weights on unknown bones.")
        rt = r["roundtrip"]
        tol = th.get("roundtrip_drift_m", 1e-4)
        g.check("roundtrip_bind_drift", rt.get("max_bind_vertex_drift_m", 1) <= tol, rt.get("max_bind_vertex_drift_m"), tol,
                "FBX re-import moved bind vertices.")
        g.check("roundtrip_bones", rt.get("max_bone_head_drift_m", 1) <= tol, rt.get("max_bone_head_drift_m"), tol, "FBX re-import moved bones.")
        if "missing_bones_after_import" in rt:
            g.check("roundtrip_bone_names", not rt["missing_bones_after_import"], rt["missing_bones_after_import"], [], "Bones lost in FBX.")
        expected = th.get("distal_digits_expected", 4)
        for side, d in r["digits"].items():
            g.check("digits_separate:" + side, d["distal_digit_sections"] >= expected, d["distal_digit_sections"], expected,
                    "Fused or missing fingers in the mesh (bones alone do not prove mesh fingers). Reuse fitted known-good "
                    "hands after two failed generated candidates.", on_fail="WARN" if d["distal_digit_sections"] >= 2 else "FAIL")
        boxes = read_json(outputs["hitboxes"])["hitboxes"]
        empty = [b["region"] for b in boxes if b["vertices"] == 0]
        g.check("hit_regions_populated", not empty, empty, [], "Hit regions without dominated vertices.")
        g.metrics["hitboxes"] = len(boxes)
        gore = read_json(outputs["gore"])["gore"]
        if gore:
            empty = [x["part"] for x in gore if x["triangles"] == 0]
            g.check("gore_regions_populated", not empty, empty, [], "Gore parts without dominated triangles.")
            g.metrics["gore_regions"] = len(gore)
        g.need_review("A valid weight table does not prove good deformation: approve at pose-screen after the stress poses.")
        return g
