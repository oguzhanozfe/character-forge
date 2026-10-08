"""Stage 8 - motion-screen ("animations in context"): pick motions from the shared library for this character,
generate only the missing ones (Kimodo), retarget onto the approved rig, screen every clip, export FBX clips."""
from __future__ import annotations

import csv
import io

from .. import library
from ..adapters import blender
from ..adapters import kimodo
from ..adapters.base import resolve_mode
from ..config import lock_root, resolve_path
from ..manifest import FAKE_FBX
from ..meshkit import analysis
from ..meshkit.motion import bone_radii, ground_clamp, retarget, screen
from ..meshkit.obj import read_obj
from ..meshkit.skeleton import Skeleton
from ..meshkit.skinning import skin_from_json
from ..presets import motion_slots
from ..util import read_json, sha256_json, write_json, write_text
from .base import Stage


def libraries_for(ws, machine):
    dirs = [resolve_path(ws.root, p) for p in machine.get("motion_libraries", [])] + [ws.dir / "motions"]
    return [lib for lib in (library.load(d) for d in dirs) if lib]


def agreement(index, baked_dir, skeleton):
    """Compare Blender's evaluated bone heads with Python's posed_world for the same baked frame."""
    from ..meshkit.motion import baked_basis
    from ..meshkit.skinning import posed_world
    from ..meshkit import vecmath as vm
    worst, rows = 0.0, {}
    for clip, probe in index.get("probes", {}).items():
        baked = read_json(baked_dir / (clip + ".baked.json"))
        world = posed_world(skeleton, baked_basis(baked, probe["frame"]))
        error = max(vm.distance(vm.mat_translation(world[n]), tuple(h)) for n, h in probe["bone_heads"].items() if n in world)
        rows[clip] = round(error, 7)
        worst = max(worst, error)
    return {"max_bone_head_disagreement_m": worst, "clips": rows,
            "meaning": "Python retarget/skinning vs Blender's evaluation of the exported keys; should be ~0"}


class MotionScreenStage(Stage):
    name = "motion-screen"
    title = "Animations in context: select, generate missing, retarget, screen"
    needs = ("rig", "unity-import")
    adapter = "kimodo"
    tool_files = ("blender/export_motions.py", "blender/_forge_common.py", "kimodo/generate_motions.py")

    def params(self, ws, character, preset, machine):
        return {"profile": character.get("motion_profile"), "slots": motion_slots(preset, character.get("motion_profile")),
                "motions": character.get("motions", {}), "prompts": preset.get("motion_prompts", {}),
                "seconds": preset.get("motion_seconds", {}), "blender_mode": resolve_mode(character, "blender"),
                "thresholds": {k: v for k, v in preset["thresholds"].items() if k.startswith(("motion", "stretch"))}}

    def extra_inputs(self, ws, character, machine):
        files = {}
        for lib in libraries_for(ws, machine):
            files["library:" + lib["name"]] = lib["index"]
            for clip in lib["clips"]:
                if clip["path"].is_file():
                    files["clip:%s/%s" % (lib["name"], clip["id"])] = clip["path"]
        return files

    def requests_for(self, ctx, missing):
        requests = list(ctx.params["motions"].get("generate", []))
        counts = {}
        for kind, region in missing:
            counts[(kind, region)] = counts.get((kind, region), 0) + 1
            prompt = ctx.params["prompts"].get(kind, "A person performs a %s motion." % kind.lower())
            prompt = prompt.replace("{region}", (region or "chest").lower())
            requests.append({"id": "%s_%s%s_%02d" % (ctx.ws.id, kind, ("_" + region) if region else "", counts[(kind, region)]),
                             "kind": kind, "region": region, "prompt": prompt, "seconds": ctx.params["seconds"].get(kind, 4),
                             "seed": int(sha256_json([ctx.ws.id, kind, region, counts[(kind, region)]])[:6], 16) % 100000,
                             "loop": kind in ("Idle", "Walk", "Run")})
        return requests

    def run(self, ctx):
        libs = libraries_for(ctx.ws, ctx.machine)
        chosen, missing = library.select(libs, ctx.params["slots"], ctx.params["motions"].get("include", []),
                                         ctx.params["motions"].get("exclude", []))
        skeleton = Skeleton.from_json(read_json(ctx.inputs["rig.skeleton"]))
        hip_height = skeleton.bones["Hips"].head[2]
        requests = self.requests_for(ctx, missing)
        generated = []
        if requests:
            gen_dir = ctx.run_dir / "generated"
            if ctx.mode == "fake":
                generated = kimodo.fake(requests, gen_dir, hip_height)
            else:
                generated = kimodo.real(ctx.machine, requests, gen_dir, ctx.out("logs/kimodo.log"), lock_root(ctx.ws.root, ctx.machine),
                                        ctx.owner(), plan=ctx.plan, mode=ctx.mode)
        for request, path in zip(requests, generated):
            chosen.append({"slot": [request["kind"], request.get("region")], "clip": {
                "id": request["id"], "kind": request["kind"], "region": request.get("region"), "path": path,
                "library": "generated:" + ("fake" if ctx.mode == "fake" else "kimodo"), "licence":
                    "procedural stand-in (fake mode)" if ctx.mode == "fake" else "Kimodo output: check model licence (SOMA-RP NVIDIA Open Model; SMPLX-RP is R&D-only)",
                "source": request["prompt"]}})
        mesh = read_obj(ctx.inputs["rig.rigged"])
        weights = skin_from_json(read_json(ctx.inputs["rig.skin"]))
        edges = analysis.unique_edges(mesh)
        radii = bone_radii(skeleton, mesh.vertices, weights)
        th = ctx.params["thresholds"]
        thresholds = {"floor_penetration_m": th.get("motion_floor_penetration_m", 0.03), "floating_m": th.get("motion_floating_m", 0.06),
                      "loop_seam_m": th.get("motion_loop_seam_m", 0.02), "stretch_red_flag": th.get("stretch_red_flag", 3.0)}
        baked_dir = ctx.run_dir / "baked"
        rows, plan = [], []
        for entry in chosen:
            clip = entry["clip"]
            baked = ground_clamp(retarget(read_json(clip["path"]), skeleton, in_place=True), skeleton, radii)
            write_json(baked_dir / (clip["id"] + ".baked.json"), baked)
            result = screen(baked, skeleton, mesh.vertices, weights, edges, ctx.height, thresholds=thresholds)
            result.update(library=clip.get("library"), licence=clip.get("licence"), ground_clamp_m=baked.get("ground_clamp_max_m"))
            rows.append(result)
            plan.append({"slot": entry["slot"], "clip": clip["id"], "library": clip.get("library"), "licence": clip.get("licence"),
                         "source": clip.get("source"), "loop": baked["loop"], "impact_seconds": baked["events"].get("impact_seconds"),
                         "suggested_speed_m_s": baked["suggested_speed_m_s"]})
        outputs = {"plan": write_json(ctx.out("motion-plan.json"), {"profile": ctx.params["profile"], "slots": ctx.params["slots"],
                                                                     "missing_after_library": missing, "generated": requests, "clips": plan}),
                   "report": write_json(ctx.out("motion-report.json"), {"clips": rows})}
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(["clip", "kind", "region", "status", "lowest_point_m", "floor_penetration_m", "loop_seam_m", "max_edge_stretch",
                         "attack_reach_per_height", "library", "problems"])
        for r in rows:
            writer.writerow([r["clip"], r["kind"], r["region"], r["status"], r["lowest_point_m"], r["floor_penetration_m"], r["loop_seam_m"],
                             r["max_edge_stretch"], r["attack_reach_per_height"], r["library"], "; ".join(r["problems"])])
        outputs["csv"] = write_text(ctx.out("motion-report.csv"), buffer.getvalue())
        motions_dir = ctx.run_dir / "Motions"
        motions_dir.mkdir(parents=True, exist_ok=True)
        if ctx.params["blender_mode"] != "fake" and "rig.blend" in ctx.inputs:
            blender.run(ctx.machine, "export_motions.py", ["--rig", ctx.inputs["rig.blend"], "--baked-dir", baked_dir,
                                                           "--output-dir", motions_dir, "--id", ctx.ws.id],
                        ctx.out("logs/export_motions.log"), plan=ctx.plan, mode=ctx.params["blender_mode"],
                        expect=[motions_dir / ("%s@%s.fbx" % (ctx.ws.id, p["clip"])) for p in plan])
        else:
            for p in plan:
                (motions_dir / ("%s@%s.fbx" % (ctx.ws.id, p["clip"]))).write_bytes(FAKE_FBX)
        for p in plan:
            outputs["fbx." + p["clip"]] = motions_dir / ("%s@%s.fbx" % (ctx.ws.id, p["clip"]))
        index = motions_dir / "export-index.json"
        if index.is_file():
            outputs["agreement"] = write_json(ctx.out("blender-agreement.json"), agreement(read_json(index), baked_dir, skeleton))
        return outputs

    def gate(self, ctx, outputs):
        g = ctx.gate()
        plan = read_json(outputs["plan"])
        rows = read_json(outputs["report"])["clips"]
        filled = len(plan["clips"])
        g.check("slots_filled", filled >= len(plan["slots"]), filled, len(plan["slots"]), "Motion slots left empty.")
        g.metrics.update(clips=filled, generated=len(plan["generated"]), from_library=filled - len(plan["generated"]))
        for r in rows:
            g.check("clip:" + r["clip"], r["status"] == "PASS", r["problems"] or "ok", "no flags", "; ".join(r["problems"]),
                    on_fail="FAIL" if r["status"] == "FAIL" else "WARN")
            if r["status"] != "PASS":
                g.view("clip-" + r["clip"], kind="motion", pose=r["clip"], reason="; ".join(r["problems"]))
        unknown = [p["clip"] for p in plan["clips"] if not p.get("licence") or "unknown" in str(p.get("licence")).lower()]
        g.check("clip_provenance", not unknown, unknown, [], "Clips without recorded licence/provenance.", on_fail="WARN")
        if plan["generated"]:
            g.info("generated_clips", [x["id"] for x in plan["generated"]], "Generated because the library lacked these slots.")
        if any(p["library"] and str(p["library"]).startswith("generated:fake") for p in plan["clips"]):
            g.check("real_motion", False, "procedural stand-ins", "library or Kimodo clips", "Fake-mode clips are smoke-test quality.",
                    on_fail="WARN")
        if "agreement" in outputs:
            a = read_json(outputs["agreement"])
            g.check("python_blender_agreement", a["max_bone_head_disagreement_m"] < 1e-3, a["max_bone_head_disagreement_m"], 1e-3,
                    "Exported keys do not reproduce the screened pose: retarget/export convention mismatch.")
        g.need_review("Watch each new/flagged clip on this character (Unity turntable preview > Motion preview): attack contact frame, "
                      "feet sliding, hands/fingers, loop seams. Numerical PASS does not approve feel.")
        return g
