"""Stage 9 - package: final forms only (FBX, runtime textures, motion FBX, manifest, concise receipt)."""
from __future__ import annotations

import shutil

from .. import __version__, approvals, manifest, packaging
from ..util import now, read_json, sha256_file, write_json, write_text
from .base import Stage

README = """{id} - packaged by character-forge {version}

Import into Unity: copy this folder under Assets/ (e.g. Assets/Characters/{id}/), then
Tools > Character Forge > Import Packaged Character and pick character.manifest.json.
Only final forms are included. Editable sources and review images stay in the character workspace.
"""


class PackageStage(Stage):
    name = "package"
    title = "Package final forms"
    needs = ("reference", "reconstruct", "preflight", "lowmesh", "rig", "pose-screen", "unity-import", "motion-screen")
    adapter = "python"

    def params(self, ws, character, preset, machine):
        return {"max_mb": preset["budgets"].get("max_package_mb")}

    def run(self, ctx):
        target = ctx.run_dir / "package"
        if target.exists():
            shutil.rmtree(target)
        unity_manifest = read_json(ctx.inputs["unity-import.candidate"])
        model_mode = unity_manifest.get("mode", "fake")
        manifest.stage_model(target, ctx.ws, ctx.inputs, model_mode)
        plan = read_json(ctx.inputs["motion-screen.plan"])
        (target / "Motions").mkdir(exist_ok=True)
        motions = []
        for clip in plan["clips"]:
            name = "%s@%s.fbx" % (ctx.ws.id, clip["clip"])
            shutil.copyfile(ctx.inputs["motion-screen.fbx." + clip["clip"]], target / "Motions" / name)
            motions.append({"id": clip["clip"], "kind": clip["slot"][0], "region": clip["slot"][1], "file": "Motions/" + name,
                            "loop": clip["loop"], "impact_seconds": clip.get("impact_seconds"),
                            "suggested_speed_m_s": clip.get("suggested_speed_m_s"), "licence": clip.get("licence")})
        data = manifest.build(ctx.ws, ctx.character, ctx.preset, ctx.inputs, model_mode, motions)
        manifest.write(target, data)
        write_text(target / "README.txt", README.format(id=ctx.ws.id, version=__version__))
        stages = {}
        for stage, record in ctx.upstream.items():
            gate = read_json(ctx.ws.stage_dir(stage) / "runs" / record["run"] / "gate.json")
            approval = approvals.latest(ctx.ws, stage, record["run"])
            stages[stage] = {"run": record["run"], "mode": record["mode"], "gate": gate["status"],
                             "approval": {k: approval[k] for k in ("decision", "by", "reviewer", "note", "utc", "waived_failures")} if approval else None}
        receipt = {"format": "character-forge/receipt@1", "character": ctx.ws.id, "preset": ctx.preset["name"], "created": now(),
                   "forge_version": __version__, "mode": model_mode, "brief": ctx.character["brief"],
                   "references": [{k: r.get(k) for k in ("view", "sha256", "provenance")} for r in ctx.character.get("references", [])],
                   "reconstruction": read_json(ctx.inputs["reconstruct.receipt"]), "stages": stages,
                   "motions": {"total": len(motions), "generated": len(plan["generated"])},
                   "files": {}, "limits": ["Automated gates measure risk; owner appearance/feel approval is separate.",
                                           "Third-party tool/model licences: see LICENSE-NOTES.md and the reconstruction licence above."]}
        write_json(target / "receipt.json", receipt)
        receipt["files"] = {p.relative_to(target).as_posix(): sha256_file(p) for p in sorted(target.rglob("*"))
                            if p.is_file() and p.name != "receipt.json"}
        write_json(target / "receipt.json", receipt)
        packaging.verify(target, ctx.ws.id, ctx.params["max_mb"])
        published = ctx.ws.packages_dir()
        if published.exists():
            shutil.rmtree(published)
        shutil.copytree(target, published)
        return {"package": target / "character.manifest.json", "receipt": target / "receipt.json"}

    def gate(self, ctx, outputs):
        g = ctx.gate()
        target = outputs["package"].parent
        issues = packaging.problems(target, ctx.ws.id, ctx.params["max_mb"])
        g.check("final_forms_only", not issues, issues, [], "Package contains intermediates or unexpected files.")
        receipt = read_json(outputs["receipt"])
        g.metrics.update(files=len(receipt["files"]), published=str(ctx.ws.packages_dir()))
        if receipt["mode"] == "fake":
            g.check("real_assets", False, "fake placeholders", "real FBX", "Fake package: placeholders are not importable.", on_fail="WARN")
        return g
