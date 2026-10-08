"""Compact contact sheet for the views the gates requested (only those; never a blanket re-render).

Real mode with Blender renders shaded views through blender/contact_sheet.py; otherwise the pure-Python
rasterizer draws flat-shaded thumbnails, which is enough for silhouettes, poses and gross defects."""
from __future__ import annotations

from . import runner
from .adapters import blender
from .meshkit import raster
from .meshkit.motion import baked_basis
from .meshkit.obj import read_obj
from .meshkit.skeleton import Skeleton
from .meshkit.skinning import deform, ops_to_basis, skin_from_json, skin_matrices, stress_pose_ops
from .util import read_json

MAX_TILES = 16


def _run_dir(ws, stage, info):
    record = info[stage].get("run")
    return ws.stage_dir(stage) / "runs" / record["run"] if record and record.get("status") == "done" else None


def render_sheet(ws, mode=None):
    info = runner.evaluate(ws, mode)
    request = read_json(ws.dir / "gates" / "contact-sheet-request.json")
    views = request["views"][:MAX_TILES]
    out = ws.dir / "gates" / "contact-sheet.png"
    rig_dir = _run_dir(ws, "rig", info)
    machine = ws.machine
    if info["rig"].get("mode") == "real" and rig_dir and (rig_dir / "rig.blend").is_file() and machine.get("blender"):
        args = ["--rig", rig_dir / "rig.blend", "--request", ws.dir / "gates" / "contact-sheet-request.json", "--output", out]
        pose_dir = _run_dir(ws, "pose-screen", info)
        if pose_dir and (pose_dir / "stress-poses.json").is_file():
            args += ["--poses", pose_dir / "stress-poses.json"]
        blender.run(machine, "contact_sheet.py", args, ws.dir / "gates" / "contact-sheet.log", expect=[out])
        return out
    static_dir = _run_dir(ws, "preflight", info)
    mesh = read_obj(rig_dir / "rigged.obj") if rig_dir else (read_obj(static_dir / "static.obj") if static_dir else None)
    if mesh is None:
        raise RuntimeError("Nothing to render yet: run at least the preflight stage.")
    tris = [t for _, t, _ in mesh.triangles()]
    skeleton = Skeleton.from_json(read_json(rig_dir / "skeleton.json")) if rig_dir else None
    weights = skin_from_json(read_json(rig_dir / "skin.json")) if rig_dir else None
    motion_dir = _run_dir(ws, "motion-screen", info)
    focus_bones = {"Head": ("Head", "Neck"), "Hands": ("LeftHand", "LeftThumb", "LeftIndex", "LeftMiddle", "LeftRing", "LeftLittle"),
                   "LeftHand": ("LeftHand", "LeftThumb", "LeftIndex", "LeftMiddle", "LeftRing", "LeftLittle")}
    dominant = [max(row, key=lambda item: item[1])[0] if row else "" for row in weights] if weights else None

    def window_for(points, focus, view):
        if not focus or focus not in focus_bones:
            return None
        if dominant is None:
            return None
        chosen = [raster.rotate_z(p, raster.VIEWS.get(view, 0.0)) for p, d in zip(points, dominant) if d.startswith(focus_bones[focus])]
        if not chosen:
            return None
        xs, zs = [p[0] for p in chosen], [p[2] for p in chosen]
        span = max(max(xs) - min(xs), max(zs) - min(zs), 0.05) * 1.3
        return ((max(xs) + min(xs)) / 2, (max(zs) + min(zs)) / 2, span)

    tiles, seen = [], set()
    for v in views:
        key = (v["name"], v["kind"], v.get("pose"))
        if key in seen:
            continue
        seen.add(key)
        label = v["name"]
        points = mesh.vertices
        view = v["name"] if v["name"] in raster.VIEWS else "front"
        if v["kind"] == "pose" and skeleton:
            points = deform(mesh.vertices, weights, skin_matrices(skeleton, ops_to_basis(skeleton, stress_pose_ops(v["pose"]))))
        elif v["kind"] == "motion" and skeleton and motion_dir and (motion_dir / "baked" / (v["pose"] + ".baked.json")).is_file():
            baked = read_json(motion_dir / "baked" / (v["pose"] + ".baked.json"))
            points = deform(mesh.vertices, weights, skin_matrices(skeleton, baked_basis(baked, baked["frames"] // 2)))
        elif v["kind"] not in ("static", "pose", "motion"):
            continue
        tiles.append((label, raster.render(points, tris, view, 160, window=window_for(points, v.get("focus"), view))[2]))
    if not tiles:
        tiles = [(name, raster.render(mesh.vertices, tris, name, 160)[2]) for name in ("front", "side", "three_quarter")]
    return raster.contact_sheet(out, tiles, columns=4)
