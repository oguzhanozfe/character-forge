"""Stage 6 - pose-screen: the 13 controlled stress poses on the final rig, numerically, plus review views."""
from __future__ import annotations

import csv
import io

from ..adapters import blender
from ..meshkit import analysis, raster
from ..meshkit import vecmath as vm
from ..meshkit.obj import read_obj
from ..meshkit.skeleton import FINGERS, Skeleton
from ..meshkit.skinning import (STRESS_POSES, STRESS_RENDERS, deform, ops_to_basis, posed_world, skin_from_json, skin_matrices,
                                  stress_pose_ops, stress_poses_json)
from ..util import read_json, write_json, write_text
from .base import Stage


def arm_chain(side):
    return {side + "UpperArm", side + "LowerArm", side + "ForearmTwist", side + "Hand"} | {
        side + f + s for f in FINGERS for s in ("Proximal", "Intermediate", "Distal")}


def cross_influence(skeleton: Skeleton, vertices, weights, factor=2.0, min_weight=0.25, limb_radius_fraction=0.05):
    """Vertices that follow an arm but sit far from it (coat pockets/thigh cloth riding the arm).

    The distance limit uses an anatomical prior (limb radius ~5 % of height) rather than radii measured from the
    weights themselves, which bad weights would inflate."""
    height = max(p[2] for p in skeleton.landmarks.values()) if skeleton.landmarks else max(b.tail[2] for b in skeleton.bones.values())
    limit = factor * limb_radius_fraction * height
    flagged = []
    for side in ("Left", "Right"):
        chain = arm_chain(side)
        segments = [(skeleton.bones[n].head, skeleton.bones[n].tail) for n in chain if n in skeleton.bones]
        for index, (v, row) in enumerate(zip(vertices, weights)):
            share = sum(w for n, w in row if n in chain)
            if share >= min_weight:
                d = min(vm.point_segment_distance(v, a, b)[0] for a, b in segments)
                if d > limit:
                    flagged.append((index, side, round(d, 4), round(share, 3)))
    return flagged


def seam_probes(mesh, skeleton, posed_by_pose, height):
    """Open boundaries of different components meeting near wrists/neck: measure gap growth through poses."""
    weld = analysis.weld_map(mesh.vertices)
    edges = analysis.polygon_edges(mesh, weld)
    boundary = {v for (a, b), c in edges.items() if c == 1 for v in (a, b)}
    if not boundary:
        return {"open_boundaries": 0, "note": "closed mesh: no open seams to probe"}
    comps = analysis.components(mesh, weld)
    comp_of = {v: i for i, c in enumerate(comps) for v in c}
    result = {"open_boundaries": len(boundary), "probes": {}}
    for joint in ("LeftHand", "RightHand", "Neck"):
        if joint not in skeleton.bones:
            continue
        centre = skeleton.bones[joint].head
        near = [v for v in boundary if vm.distance(mesh.vertices[v], centre) < 0.06 * height]
        groups = {}
        for v in near:
            groups.setdefault(comp_of.get(v), []).append(v)
        if len(groups) < 2:
            continue
        a, b = sorted(groups.values(), key=len, reverse=True)[:2]
        worst = 0.0
        for posed in posed_by_pose.values():
            gap = analysis.seam_gap([mesh.vertices[i] for i in a], [posed[i] for i in a], [mesh.vertices[i] for i in b], [posed[i] for i in b])
            worst = max(worst, gap or 0.0)
        result["probes"][joint] = {"boundary_vertices": [len(a), len(b)], "max_gap_growth_m": round(worst, 4)}
    return result


class PoseScreenStage(Stage):
    name = "pose-screen"
    title = "13 stress poses on the final rig"
    needs = ("rig",)
    adapter = "blender"
    tool_files = ("blender/pose_render.py", "blender/_forge_common.py")

    def params(self, ws, character, preset, machine):
        return {"poses": STRESS_POSES, "renders": STRESS_RENDERS,
                "thresholds": {k: v for k, v in preset["thresholds"].items() if k.startswith(("stretch", "cross", "seam"))}}

    def run(self, ctx):
        mesh = read_obj(ctx.inputs["rig.rigged"])
        skeleton = Skeleton.from_json(read_json(ctx.inputs["rig.skeleton"]))
        weights = skin_from_json(read_json(ctx.inputs["rig.skin"]))
        th = ctx.thresholds
        edges = analysis.unique_edges(mesh)
        rows, posed_by_pose, tiles = [], {}, []
        tris = [t for _, t, _ in mesh.triangles()]
        poses_file = write_json(ctx.out("stress-poses.json"), stress_poses_json(ctx.height))
        for pose in STRESS_POSES:
            basis = ops_to_basis(skeleton, stress_pose_ops(pose, ctx.height))
            posed = deform(mesh.vertices, weights, skin_matrices(skeleton, basis))
            posed_by_pose[pose] = posed
            finite = analysis.all_finite(posed)
            st = analysis.edge_stretch(mesh.vertices, posed, edges, red_flag=th.get("stretch_red_flag", 3.0)) if finite else {}
            rows.append({"pose": pose, "finite": finite, "max_ratio": st.get("max_ratio"), "min_ratio": st.get("min_ratio"),
                         "edges_over_red_flag": st.get("over_red_flag"), "worst": st.get("worst", [])[:5],
                         "lowest_z_m": round(min(p[2] for p in posed), 4) if finite else None})
            if finite:
                tiles.append((pose, raster.render(posed, tris, "front", 128)[2]))
        flagged = cross_influence(skeleton, mesh.vertices, weights)
        report = {"poses": rows, "cross_influence": {"flagged_vertices": len(flagged), "fraction": round(len(flagged) / max(1, len(mesh.vertices)), 5),
                                                     "examples": flagged[:12]},
                  "seams": seam_probes(mesh, skeleton, posed_by_pose, ctx.height)}
        outputs = {"report": write_json(ctx.out("pose-report.json"), report), "poses": poses_file}
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(["pose", "finite", "max_ratio", "min_ratio", "edges_over_red_flag", "lowest_z_m"])
        for r in rows:
            writer.writerow([r["pose"], r["finite"], r["max_ratio"], r["min_ratio"], r["edges_over_red_flag"], r["lowest_z_m"]])
        outputs["csv"] = write_text(ctx.out("pose-report.csv"), buffer.getvalue())
        if tiles:
            outputs["sheet"] = raster.contact_sheet(ctx.out("pose-sheet.png"), tiles, columns=7)
        if ctx.mode != "fake" and "rig.blend" in ctx.inputs:
            blender.run(ctx.machine, "pose_render.py", ["--rig", ctx.inputs["rig.blend"], "--poses", poses_file,
                                                        "--output-dir", ctx.run_dir / "renders", "--height", ctx.height],
                        ctx.out("logs/pose_render.log"), expect=[ctx.run_dir / "renders"], plan=ctx.plan, mode=ctx.mode)
            outputs["renders"] = ctx.run_dir / "renders" / "index.json"
            worst = 0.0
            for row in read_json(outputs["renders"])["renders"]:
                world = posed_world(skeleton, ops_to_basis(skeleton, stress_pose_ops(row["pose"], ctx.height)))
                worst = max([worst] + [vm.distance(vm.mat_translation(world[n]), tuple(h)) for n, h in row.get("bone_heads", {}).items() if n in world])
            report["blender_pose_agreement_m"] = worst
            write_json(outputs["report"], report)
        return outputs

    def gate(self, ctx, outputs):
        g = ctx.gate()
        th = ctx.thresholds
        report = read_json(outputs["report"])
        red = th.get("stretch_red_flag", 3.0)
        g.metrics["poses"] = [{k: r[k] for k in ("pose", "max_ratio", "edges_over_red_flag")} for r in report["poses"]]
        for r in report["poses"]:
            g.check("finite:" + r["pose"], r["finite"], None, None, "Nonfinite skinned vertices.")
            if not r["finite"]:
                continue
            g.check("stretch_hard:" + r["pose"], r["edges_over_red_flag"] <= th.get("stretch_edges_fail", 100) and
                    r["max_ratio"] <= th.get("stretch_max_ratio_fail", 8.0), [r["edges_over_red_flag"], r["max_ratio"]],
                    [th.get("stretch_edges_fail", 100), th.get("stretch_max_ratio_fail", 8.0)],
                    "Severe stretching (the Z29 coat failure had 1,046 edges > 3x, worst 21x).")
            g.check("stretch_red_flag:" + r["pose"], r["edges_over_red_flag"] == 0, r["edges_over_red_flag"], 0,
                    "Edges stretched beyond %.1fx: inspect worst vertices %s." % (red, [w["vertices"] for w in r["worst"][:3]]), on_fail="WARN")
            if r["edges_over_red_flag"]:
                g.view("pose-" + r["pose"], kind="pose", pose=r["pose"], reason="stretch red flag")
        ci = report["cross_influence"]
        g.check("cross_influence", ci["fraction"] <= th.get("cross_influence_fraction_warn", 0.005), ci["fraction"],
                th.get("cross_influence_fraction_warn", 0.005), "Cloth/torso vertices following the arm chain.", on_fail="WARN")
        for joint, probe in report["seams"].get("probes", {}).items():
            g.check("seam_gap:" + joint, probe["max_gap_growth_m"] <= th.get("seam_gap_growth_warn_m", 0.01), probe["max_gap_growth_m"],
                    th.get("seam_gap_growth_warn_m", 0.01), "Open seam opens up in poses.", on_fail="WARN")
        if "blender_pose_agreement_m" in report:
            g.check("python_blender_pose_agreement", report["blender_pose_agreement_m"] < 1e-3, report["blender_pose_agreement_m"], 1e-3,
                    "Blender's posed rig differs from the screened pose definition.")
        g.need_review("Inspect pose-sheet.png (and Blender renders in real mode): elbows, fists/claws, wrist twist, crouch and "
                      "cross-body. Finite numbers and a passing table do not approve appearance.")
        for pose in STRESS_RENDERS:
            g.view("pose-" + pose, kind="pose", pose=pose, focus="LeftHand" if pose in ("fist", "claw", "twist", "wrist") else None,
                   reason="standard stress review")
        return g
