"""Stage 4 - lowmesh: budgeted game mesh, UVs with head texel priority, baked runtime textures."""
from __future__ import annotations

import shutil

from ..adapters import blender
from ..meshkit import analysis, raster
from ..meshkit.obj import read_obj
from ..util import read_json, write_json
from .base import Stage

# Runtime channels: BaseColor (sRGB), Normal (tangent, OpenGL +Y), MetallicSmoothness (R metallic, A smoothness).
CHANNELS = {"BaseColor": (128, 118, 104, 255), "Normal": (128, 128, 255, 255), "MetallicSmoothness": (0, 0, 0, 77)}


class LowmeshStage(Stage):
    name = "lowmesh"
    title = "Low mesh, UV and bake"
    needs = ("preflight",)
    adapter = "blender"
    tool_files = ("blender/lowmesh.py", "blender/_forge_common.py")

    def params(self, ws, character, preset, machine):
        p = character["params"]
        return {"triangle_budget": int(p.get("triangle_budget") or preset["budgets"]["triangles_lod0"]),
                "texture_size": int(p.get("texture_size") or preset["budgets"]["texture_size"]),
                "bake": bool(p.get("bake_normals", True)), "max_materials": preset["budgets"]["max_materials"]}

    def run(self, ctx):
        outputs = {}
        textures = ctx.run_dir / "Textures"
        if ctx.mode == "fake":
            shutil.copyfile(ctx.inputs["preflight.static"], ctx.out("low.obj"))
            textures.mkdir(parents=True, exist_ok=True)
            for channel, colour in CHANNELS.items():
                raster.solid_png(textures / ("%s_%s.png" % (ctx.ws.id, channel)), 64, colour)
            write_json(ctx.out("lowmesh-blender.json"), {"mode": "fake", "decimated": False,
                                                         "note": "fake textures are flat placeholders"})
        else:
            args = ["--source", ctx.inputs.get("preflight.blend", ctx.inputs["preflight.static"]), "--output-dir", ctx.run_dir,
                    "--id", ctx.ws.id, "--triangles", ctx.params["triangle_budget"], "--texture-size", ctx.params["texture_size"]]
            if not ctx.params["bake"]:
                args.append("--no-bake")
            blender.run(ctx.machine, "lowmesh.py", args, ctx.out("logs/lowmesh.log"),
                        expect=[ctx.run_dir / "low.obj", ctx.run_dir / "low.blend"], plan=ctx.plan, mode=ctx.mode)
            outputs["blend"] = ctx.run_dir / "low.blend"
        outputs["low"] = ctx.run_dir / "low.obj"
        outputs["blender_report"] = ctx.run_dir / "lowmesh-blender.json"
        for png in sorted(textures.glob("*.png")):
            outputs["texture." + png.stem.split("_")[-1]] = png
        mesh = read_obj(outputs["low"])
        landmarks = {k: tuple(v) for k, v in read_json(ctx.inputs["preflight.landmarks"])["landmarks"].items()}
        report = {"triangles": mesh.triangle_count(), "materials": sorted(set(mesh.face_materials)),
                  "uv": analysis.uv_report(mesh, landmarks, ctx.params["texture_size"])}
        outputs["analysis"] = write_json(ctx.out("analysis.json"), report)
        return outputs

    def gate(self, ctx, outputs):
        g = ctx.gate()
        th = ctx.thresholds
        report = read_json(outputs["analysis"])
        uv = report["uv"]
        g.metrics.update(triangles=report["triangles"], materials=report["materials"], uv=uv)
        g.check("triangle_budget", report["triangles"] <= ctx.params["triangle_budget"], report["triangles"], ctx.params["triangle_budget"],
                "Over the LOD0 budget.")
        g.check("material_count", len(report["materials"]) <= ctx.params["max_materials"], len(report["materials"]),
                ctx.params["max_materials"], "More material sets than the budget.", on_fail="WARN")
        g.check("uv_present", uv["faces_missing_uv"] == 0, uv["faces_missing_uv"], 0, "Faces without UVs.")
        g.check("uv_finite", uv["nonfinite_uv_triangles"] == 0, uv["nonfinite_uv_triangles"], 0, "Nonfinite UVs.")
        g.check("uv_in_0_1", uv["triangles_outside_0_1"] == 0, uv["triangles_outside_0_1"], 0, "UVs outside 0..1 (tiling?)", on_fail="WARN")
        head_sub = uv["subpixel_triangles_head"]
        g.check("face_subpixel_triangles", head_sub <= th.get("head_subpixel_triangles_fail", 500), head_sub,
                th.get("head_subpixel_triangles_fail", 500), "Face triangles smaller than a texel: bald/black patches likely.")
        g.check("face_subpixel_triangles_clean", head_sub <= th.get("head_subpixel_triangles_warn", 0), head_sub,
                th.get("head_subpixel_triangles_warn", 0), "Some face triangles are subpixel.", on_fail="WARN")
        g.check("face_texel_priority", uv["head_to_body_density_ratio"] >= th.get("head_to_body_density_min", 1.2),
                uv["head_to_body_density_ratio"], th.get("head_to_body_density_min", 1.2),
                "Head texel density should exceed the body's.", on_fail="WARN")
        g.check("tiny_uv_islands", uv["tiny_uv_islands"] <= th.get("tiny_uv_islands_warn", 0), uv["tiny_uv_islands"],
                th.get("tiny_uv_islands_warn", 0), "Microscopic UV islands.", on_fail="WARN")
        channels = sorted(k.split(".", 1)[1] for k in outputs if k.startswith("texture."))
        g.check("runtime_textures", bool(channels), channels, "BaseColor (+Normal, MaskMap)", "No runtime textures written.")
        g.need_review("Inspect the face close-up under neutral light for black/bald patches and seams; investigate with UV/material "
                      "masks rather than black-pixel counting (eyes and decay are dark on purpose).")
        g.view("face", kind="static", focus="Head", reason="texel density / bake")
        return g
