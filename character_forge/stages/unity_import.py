"""Stage 7 - unity-import: import the candidate, build its own Humanoid Avatar, hitboxes and gore regions."""
from __future__ import annotations

from .. import manifest
from ..adapters import unity
from ..config import lock_root
from ..presets import required_bones
from ..util import read_json
from .base import Stage


class UnityImportStage(Stage):
    name = "unity-import"
    title = "Unity import: Avatar, materials, hitboxes, gore regions"
    needs = ("lowmesh", "rig", "pose-screen")
    adapter = "unity"
    tool_files = ("unity/com.characterforge.core/Editor/ForgeBatch.cs", "unity/com.characterforge.core/Editor/CharacterImporter.cs")

    def params(self, ws, character, preset, machine):
        return {"required_bones": required_bones(preset), "hit_regions": sorted(preset.get("hit_regions", {})),
                "gore_regions": sorted(preset.get("gore_regions", {})), "unity_project": machine.get("unity_project")}

    def run(self, ctx):
        candidate = ctx.run_dir / "candidate"
        model_mode = "fake" if "rig.fbx" not in ctx.inputs else "real"
        manifest.stage_model(candidate, ctx.ws, ctx.inputs, model_mode)
        manifest.write(candidate, manifest.build(ctx.ws, ctx.character, ctx.preset, ctx.inputs, model_mode))
        report_path = ctx.out("unity-report.json")
        if ctx.mode == "fake":
            unity.fake(candidate, report_path, ctx.params["required_bones"], ctx.params["hit_regions"], ctx.params["gore_regions"])
        else:
            unity.real(ctx.machine, ctx.ws.root, candidate, ctx.ws.id, report_path, ctx.out("logs/unity.log"),
                       lock_root(ctx.ws.root, ctx.machine), ctx.owner(), plan=ctx.plan, mode=ctx.mode)
        return {"candidate": candidate / "character.manifest.json", "report": report_path}

    def gate(self, ctx, outputs):
        g = ctx.gate()
        r = read_json(outputs["report"])
        g.metrics.update({k: r.get(k) for k in ("unity_version", "mapped_human_bones", "hitboxes", "gore_regions", "materials", "prefab")})
        g.check("avatar_valid", r.get("avatar_valid") is True, r.get("avatar_valid"), True, "Unity rejected the Avatar.")
        g.check("avatar_human", r.get("avatar_human") is True, r.get("avatar_human"), True, "Avatar is not Humanoid.")
        g.check("required_bones_mapped", not r.get("missing_required_bones"), r.get("missing_required_bones"), [], "Unmapped bones.")
        g.check("hitboxes", r.get("hitboxes") == len(ctx.params["hit_regions"]), r.get("hitboxes"), len(ctx.params["hit_regions"]),
                "Regional hitbox count differs from the preset.")
        g.check("gore_regions", r.get("gore_regions") == len(ctx.params["gore_regions"]), r.get("gore_regions"),
                len(ctx.params["gore_regions"]), "Gore region count differs from the preset.")
        g.check("import_errors", not r.get("errors"), r.get("errors"), [], "Unity reported import errors.")
        if r.get("mode") == "fake":
            g.check("real_unity_import", False, "fake", "real", "Contract checked from the manifest only; import in Unity before shipping.",
                    on_fail="WARN")
        g.need_review("Open the generated prefab in the turntable preview (Tools > Character Forge > Turntable Preview): materials, "
                      "scale, facing, hitbox capsules and gore markers. A valid Avatar does not establish good weights.")
        g.view("unity-turntable", kind="unity", reason="engine appearance")
        return g
