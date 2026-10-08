"""Stage 2 - reconstruct: one image-to-3D candidate from the configured backend (single GPU queue)."""
from __future__ import annotations

from ..adapters import reconstruct as adapter
from ..config import lock_root
from ..util import write_json
from .base import Stage


class ReconstructStage(Stage):
    name = "reconstruct"
    title = "Image-to-3D source candidate"
    needs = ("reference",)
    adapter = "reconstruct"

    def params(self, ws, character, preset, machine):
        backend = character["params"].get("reconstruct_backend") or machine["reconstruct"]["default_backend"]
        return {"backend": backend, "seed": int(character["params"]["seed"]), "height_m": float(character["params"]["height_m"]),
                "backend_config": machine["reconstruct"]["backends"].get(backend, {}),
                "licence_ack": sorted(character["params"].get("licence_ack", []))}

    def run(self, ctx):
        if ctx.mode == "fake":
            result = adapter.fake(ctx.run_dir, ctx.params["seed"], ctx.params["height_m"])
        else:
            reference = ctx.inputs.get("reference.ref.front")
            result = adapter.real(ctx.machine, ctx.params["backend"], reference, ctx.run_dir, ctx.params["seed"],
                                  ctx.out("logs/reconstruct.log"), lock_root(ctx.ws.root, ctx.machine), ctx.owner(),
                                  plan=ctx.plan, mode=ctx.mode, licence_ack=ctx.params["licence_ack"])
        outputs = {"mesh": result["mesh"], "receipt": write_json(ctx.out("reconstruct-receipt.json"), result["receipt"])}
        if result.get("landmarks"):
            outputs["landmarks"] = result["landmarks"]
        return outputs

    def gate(self, ctx, outputs):
        g = ctx.gate()
        mesh = outputs["mesh"]
        size = mesh.stat().st_size
        g.check("mesh_written", size > 1024, size, "> 1 KiB", "Backend wrote an empty or tiny file.")
        if mesh.suffix == ".glb":
            g.check("glb_magic", mesh.read_bytes()[:4] == b"glTF", None, "glTF", "Not a binary glTF.")
        backend = ctx.params["backend"] if ctx.mode != "fake" else "fake"
        cfg = ctx.machine["reconstruct"]["backends"].get(backend, {})
        if cfg.get("requires_licence_ack"):
            g.check("licence_territory_clear", False, backend, "worldwide-cleared backend",
                    cfg.get("licence", "") + " Do not ship outputs worldwide without clearance.", on_fail="WARN")
        g.need_review("Open the raw candidate: garment construction, face, hands and back are this character's own and plausible. "
                      "Stop after two failed anatomical candidates and reuse fitted known-good parts instead.")
        return g
