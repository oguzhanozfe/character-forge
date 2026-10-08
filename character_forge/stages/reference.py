"""Stage 1 - reference: validate supplied reference images or emit a reference request for the agent/human."""
from __future__ import annotations

from ..imageinfo import image_info
from ..meshkit import raster
from ..meshkit.synth import proportions_from_seed, synthetic_humanoid
from ..util import sha256_file, write_json
from .base import Stage

VIEW_PROMPTS = {
    "front": "full-body front view, neutral A-pose, arms about 45 degrees down, hands clearly away from the thighs, feet slightly apart",
    "side": "full-body left side view, same A-pose, same clothing construction",
    "back": "full-body back view, same A-pose, same clothing construction",
    "portrait": "head and shoulders portrait, front view, neutral expression for this identity, even light",
}


class ReferenceStage(Stage):
    name = "reference"
    title = "Reference images (identity, A-pose, portrait)"
    adapter = "reconstruct"

    def params(self, ws, character, preset, machine):
        return {"brief": character["brief"], "preset": preset["name"], "guidance": preset.get("reference_guidance", [])}

    def extra_inputs(self, ws, character, machine):
        return {"ref." + r["view"]: ws.dir / r["file"] for r in character.get("references", [])}

    def run(self, ctx):
        refs = ctx.character.get("references", [])
        views = {r["view"] for r in refs}
        request = {"format": "character-forge/reference-request@1", "character": ctx.ws.id, "brief": ctx.character["brief"],
                   "guidance": ctx.preset.get("reference_guidance", []),
                   "missing_views": [v for v in ("front", "portrait", "side", "back") if v not in views],
                   "prompts": {v: "%s. %s. Plain neutral grey background, even studio light, no text, no watermark." % (
                       ctx.character["brief"], VIEW_PROMPTS[v]) for v in VIEW_PROMPTS if v not in views},
                   "how_to_add": "forge add-reference %s <image> --view <front|side|back|portrait> --provenance \"<tool/author, licence>\"" % ctx.ws.id}
        outputs = {"request": write_json(ctx.out("reference-request.json"), request)}
        rows = []
        for r in refs:
            path = ctx.ws.dir / r["file"]
            info = image_info(path)
            rows.append(dict(r, sha256_now=sha256_file(path), **info))
            outputs["ref." + r["view"]] = path
        if "front" not in views and ctx.mode == "fake":
            p = proportions_from_seed(int(ctx.character["params"]["seed"]))
            p.height = ctx.height
            mesh, _ = synthetic_humanoid(p)
            tris = [t for _, t, _ in mesh.triangles()]
            _, _, pixels, _ = raster.render(mesh.vertices, tris, "front", 256)
            outputs["ref.front"] = raster.write_png(ctx.out("fake-front.png"), pixels)
            rows.append({"view": "front", "file": "fake-front.png", "provenance": "FAKE placeholder render", "format": "png",
                         "width": 256, "height": 256})
        outputs["manifest"] = write_json(ctx.out("references.json"), {"references": rows})
        return outputs

    def gate(self, ctx, outputs):
        g = ctx.gate()
        refs = ctx.character.get("references", [])
        has_front = "ref.front" in outputs
        fake_front = has_front and not any(r["view"] == "front" for r in refs)
        g.check("front_reference_present", has_front, "front" if has_front else None, "front A-pose image",
                "Missing front reference: generate one from reference-request.json or supply an image.")
        if fake_front:
            g.check("front_reference_is_real", False, "fake placeholder", "real image", "Fake mode placeholder; not a design.", on_fail="WARN")
        for r in refs:
            info = image_info(ctx.ws.dir / r["file"])
            g.check("hash_matches:" + r["view"], sha256_file(ctx.ws.dir / r["file"]) == r["sha256"], None, None,
                    "Reference changed after it was added; re-add it.")
            longest = max(info["width"], info["height"])
            g.check("resolution:" + r["view"], longest >= 1024, longest, 1024, "Low resolution weakens faces/hands.", on_fail="WARN")
            g.check("provenance:" + r["view"], r.get("provenance", "unspecified") not in ("", "unspecified"), r.get("provenance"),
                    "tool/author + licence", "Record where the image came from and its rights.", on_fail="WARN")
        g.info("missing_optional_views", [v for v in ("portrait", "side", "back") if v not in {r["view"] for r in refs}])
        g.need_review("Identity: original fictional adult, no real-person likeness/brand/franchise; matches the brief.")
        g.need_review("Pose: neutral A-pose, hands away from thighs, armpits visible, consistent clothing across views.")
        g.view("reference-front", kind="reference", reason="identity/pose check")
        return g
