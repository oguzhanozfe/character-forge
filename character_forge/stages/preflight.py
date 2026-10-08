"""Stage 3 - preflight: normalize scale/facing, component/debris scan, completeness, landmarks, individuality."""
from __future__ import annotations

from pathlib import Path

from ..adapters import blender
from ..meshkit import analysis, raster
from ..meshkit.obj import read_obj, write_obj
from ..meshkit.skeleton import estimate_landmarks
from ..util import read_json, write_json
from .base import Stage

SILHOUETTE_VIEWS = ("front", "side", "three_quarter")
SILHOUETTE_SIZE = 128


def normalize(mesh, height):
    """Scale to height, feet on z=0, centred on x/y (fake mode / OBJ sources)."""
    lo, hi = mesh.bounds()
    scale = height / (hi[2] - lo[2])
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
    mesh.vertices = [((x - cx) * scale, (y - cy) * scale, (z - lo[2]) * scale) for x, y, z in mesh.vertices]
    return mesh, {"scale": scale, "offset": [-cx, -cy, -lo[2]]}


def apply_transform(point, transform):
    s, o = transform["scale"], transform["offset"]
    return tuple((p + d) * s for p, d in zip(point, o))


def silhouettes(mesh):
    lo, hi = mesh.bounds()
    h = hi[2] - lo[2]
    unit = [(v[0] / h, v[1] / h, (v[2] - lo[2]) / h) for v in mesh.vertices]
    tris = [t for _, t, _ in mesh.triangles()]
    out = {}
    for view in SILHOUETTE_VIEWS:
        _, _, _, mask = raster.render(unit, tris, view, SILHOUETTE_SIZE, height=1.0, shade=False)
        out[view] = raster.mask_to_rle(mask)
    return out


def roster_silhouettes(ws, machine):
    """Silhouettes of every other character's current preflight run, plus configured roster folders."""
    from ..runner import current_run
    found = []
    characters = ws.root / "characters"
    for other in sorted(p for p in characters.iterdir() if p.is_dir() and p.name != ws.id) if characters.is_dir() else []:
        try:
            from ..workspace import Workspace
            run = current_run(Workspace(ws.root, other.name), "preflight")
        except Exception:
            run = None
        if run and run.get("status") == "done":
            path = other / "stages" / "preflight" / "runs" / run["run"] / "silhouettes.json"
            if path.is_file():
                found.append((other.name, read_json(path)))
    for folder in machine.get("roster_dirs", []):
        for path in sorted(Path(folder).glob("*.silhouettes.json")):
            found.append((path.name[: -len(".silhouettes.json")], read_json(path)))
    return found


def compare(own, roster):
    rows = []
    for name, theirs in roster:
        scores = {}
        for view in SILHOUETTE_VIEWS:
            if view in own and view in theirs.get("views", {}):
                scores[view] = round(raster.iou(raster.rle_to_mask(own[view]), raster.rle_to_mask(theirs["views"][view])), 4)
        if scores:
            rows.append({"character": name, "iou": scores, "mean_iou": round(sum(scores.values()) / len(scores), 4)})
    return sorted(rows, key=lambda r: -r["mean_iou"])


class PreflightStage(Stage):
    name = "preflight"
    title = "Static preflight: scale, components, completeness, individuality"
    needs = ("reconstruct",)
    adapter = "blender"
    tool_files = ("blender/preflight.py", "blender/_forge_common.py")

    def params(self, ws, character, preset, machine):
        return {"height_m": float(character["params"]["height_m"]), "landmarks_override": character.get("landmarks_override"),
                "thresholds": {k: v for k, v in preset["thresholds"].items() if k.startswith(("debris", "height", "individuality"))}}

    def run(self, ctx):
        source = ctx.inputs["reconstruct.mesh"]
        outputs = {}
        if ctx.mode == "fake":
            mesh, transform = normalize(read_obj(source), ctx.params["height_m"])
            write_obj(mesh, ctx.out("static.obj"), header="normalized static source")
            write_json(ctx.out("preflight-blender.json"), {"mode": "python", "transform": transform})
        else:
            blender.run(ctx.machine, "preflight.py", ["--source", source, "--output-dir", ctx.run_dir, "--height", ctx.params["height_m"]],
                        ctx.out("logs/preflight.log"), expect=[ctx.run_dir / "static.obj", ctx.run_dir / "static.blend"],
                        plan=ctx.plan, mode=ctx.mode)
            outputs["blend"] = ctx.run_dir / "static.blend"
            mesh = read_obj(ctx.run_dir / "static.obj")
        outputs["static"] = ctx.run_dir / "static.obj"
        outputs["blender_report"] = ctx.run_dir / "preflight-blender.json"
        if ctx.params["landmarks_override"]:
            landmarks = {k: tuple(v) for k, v in ctx.params["landmarks_override"].items()}
            origin = "character.json landmarks_override"
        elif "reconstruct.landmarks" in ctx.inputs:
            raw = read_json(ctx.inputs["reconstruct.landmarks"])["landmarks"]
            # Backend landmarks are in source space; apply the same normalization as the mesh.
            transform = read_json(ctx.run_dir / "preflight-blender.json").get("transform", {"scale": 1.0, "offset": [0, 0, 0]})
            landmarks = {k: apply_transform(v, transform) for k, v in raw.items()}
            origin = "reconstruction backend"
        else:
            landmarks = estimate_landmarks(mesh.vertices)
            origin = "heuristic estimate (PROPOSAL): review and override in character.json if needed"
        outputs["landmarks"] = write_json(ctx.out("landmarks.json"), {"format": "character-forge/landmarks@1", "origin": origin,
                                                                     "landmarks": {k: list(v) for k, v in sorted(landmarks.items())}})
        th = ctx.thresholds
        report = {"topology": analysis.topology_report(mesh),
                  "components": analysis.component_report(mesh, landmarks, ctx.height, th.get("debris_vertex_fraction", 0.005),
                                                          th.get("debris_size_fraction", 0.03)),
                  "completeness": analysis.completeness_report(mesh, landmarks, ctx.height)}
        lo, hi = mesh.bounds()
        report["dimensions_m"] = [round(h - l, 4) for l, h in zip(lo, hi)]
        outputs["analysis"] = write_json(ctx.out("analysis.json"), report)
        sil = silhouettes(mesh)
        outputs["silhouettes"] = write_json(ctx.out("silhouettes.json"), {"format": "character-forge/silhouettes@1",
                                                                         "character": ctx.ws.id, "views": sil})
        tris = [t for _, t, _ in mesh.triangles()]
        tiles = [(view, raster.render(mesh.vertices, tris, view, 160)[2]) for view in ("front", "side", "three_quarter", "back")]
        outputs["preview"] = raster.contact_sheet(ctx.out("preview.png"), tiles, columns=4)
        return outputs

    def gate(self, ctx, outputs):
        g = ctx.gate()
        th = ctx.thresholds
        report = read_json(outputs["analysis"])
        topo = report["topology"]
        g.metrics.update(topology=topo, dimensions_m=report["dimensions_m"])
        g.check("finite_vertices", topo["nonfinite_vertices"] == 0, topo["nonfinite_vertices"], 0, "Nonfinite coordinates.")
        g.check("degenerate_triangles", topo["degenerate_triangles"] <= th.get("degenerate_triangles_warn", 0),
                topo["degenerate_triangles"], th.get("degenerate_triangles_warn", 0), "Zero-area triangles.", on_fail="WARN")
        g.check("nonmanifold_edges", topo["nonmanifold_edges"] <= th.get("nonmanifold_edges_warn", 0), topo["nonmanifold_edges"],
                th.get("nonmanifold_edges_warn", 0), "Edges shared by more than two faces.", on_fail="WARN")
        height = report["dimensions_m"][2]
        tol = th.get("height_tolerance_fraction", 0.02)
        g.check("height", abs(height - ctx.height) <= tol * ctx.height, height, ctx.height, "Normalized height differs from the brief.")
        debris = [c for c in report["components"] if c["status"] == "debris_candidate"]
        review = [c for c in report["components"] if c["status"] == "review"]
        g.metrics["components"] = len(report["components"])
        g.check("debris_candidates", not debris, [{"component": c["component"], "region": c["region"], "vertices": c["vertices"]} for c in debris],
                0, "Small detached fragments: review, then delete approved debris in a NEW source revision (never auto-delete).", on_fail="WARN")
        if review:
            g.info("small_components_in_protected_regions", [{"component": c["component"], "region": c["region"]} for c in review],
                   "Could be teeth, fingertips, buttons or gore detail: keep unless reviewed as debris.")
        missing = [k for k, v in report["completeness"].items() if not v]
        g.check("anatomy_completeness", not missing, report["completeness"], "geometry at head/hands/fingertips/feet",
                "Missing geometry near: " + ", ".join(missing) if missing else "")
        own = read_json(outputs["silhouettes"])["views"]
        rows = compare(own, roster_silhouettes(ctx.ws, ctx.machine))
        g.metrics["individuality_nearest"] = rows[:5]
        if rows:
            top = rows[0]
            g.check("individuality_not_duplicate", top["mean_iou"] < th.get("individuality_iou_fail", 0.975), top["mean_iou"],
                    th.get("individuality_iou_fail", 0.975), "Near-identical silhouette to %s." % top["character"])
            g.check("individuality_distinct", top["mean_iou"] < th.get("individuality_iou_warn", 0.93), top["mean_iou"],
                    th.get("individuality_iou_warn", 0.93), "Similar silhouette to %s: compare face/garment construction." % top["character"],
                    on_fail="WARN")
        else:
            g.info("individuality_roster", 0, "No roster neighbours yet; nothing to compare.")
        g.need_review("Look at preview.png (front/side/three-quarter/back): own garment construction, face and silhouette; "
                      "height alone never makes a character distinct.")
        g.need_review("Check landmarks.json against the mesh (origin: %s)." % read_json(outputs["landmarks"])["origin"])
        for view in ("front", "side", "three_quarter"):
            g.view(view, kind="static", reason="silhouette/identity")
        g.view("face", kind="static", focus="Head", reason="face/scalp")
        g.view("hands", kind="static", focus="Hands", reason="digit count/fusion")
        return g
