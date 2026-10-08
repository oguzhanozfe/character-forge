"""Preflight: import a reconstruction (GLB/OBJ/FBX), detect up axis, normalize height/centre/floor, extract textures,
write static.blend + static.obj (exact vertex order) + preflight-blender.json. Measures only; deletes nothing.

  blender --background --factory-startup --python-exit-code 1 --python preflight.py -- \
      --source source.glb --output-dir <run> --height 1.78 [--up auto|y|z] [--rotate-z 0]
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _forge_common as fc  # noqa: E402

import bpy  # noqa: E402
from mathutils import Matrix  # noqa: E402


def configure(p):
    p.add_argument("--source", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--height", type=float, required=True)
    p.add_argument("--up", choices=("auto", "y", "z"), default="auto")
    p.add_argument("--rotate-z", type=float, default=0.0, help="extra yaw so the character faces -Y")


def main():
    args = fc.parse(__doc__, configure)
    source, out = Path(args.source).resolve(), Path(args.output_dir).resolve()
    if not source.is_file():
        raise SystemExit("missing source " + str(source))
    if not 0.1 <= args.height <= 5.0:
        raise SystemExit("height must be 0.1..5 m")
    out.mkdir(parents=True, exist_ok=True)
    fc.reset()
    fc.import_any(source)
    meshes = fc.mesh_objects()
    if not meshes:
        raise SystemExit("no meshes in source")
    # Drop armatures/empties from generators; keep only geometry for the static stage.
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH":
            bpy.data.objects.remove(obj, do_unlink=True)
    fc.bake_transforms(meshes)
    lo, hi = fc.bounds(meshes)
    dims = [h - l for l, h in zip(lo, hi)]
    convert = args.up == "y" or (args.up == "auto" and dims[1] > dims[2] * 1.3)
    if convert:
        for obj in meshes:
            obj.data.transform(Matrix.Rotation(math.radians(90), 4, "X"))
    if args.rotate_z:
        for obj in meshes:
            obj.data.transform(Matrix.Rotation(math.radians(args.rotate_z), 4, "Z"))
    lo, hi = fc.bounds(meshes)
    scale = args.height / (hi[2] - lo[2])
    offset = [-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]]
    transform = Matrix.Scale(scale, 4) @ Matrix.Translation(offset)
    for number, obj in enumerate(meshes):
        obj.data.transform(transform)
        obj.name = "Part_%02d" % number
        for poly in obj.data.polygons:
            poly.use_smooth = True
        obj.data.update()
    (out / "Textures").mkdir(exist_ok=True)
    images = []
    for number, image in enumerate(i for i in bpy.data.images if i.type == "IMAGE" and i.size[0] > 0):
        target = out / "Textures" / ("source_%02d.png" % number)
        image.filepath_raw = str(target)
        image.file_format = "PNG"
        image.save()
        images.append({"name": image.name, "path": target.relative_to(out).as_posix(), "size": list(image.size),
                       "colorspace": image.colorspace_settings.name})
    materials = sorted({m.name for o in meshes for m in o.data.materials if m})
    fc.write_obj(meshes, out / "static.obj", header="static source from %s" % source.name)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "static.blend"))
    report = {"mode": "real", "blender": bpy.app.version_string, "source": str(source), "source_sha256": fc.digest(source),
              "raw_dimensions": dims, "y_up_converted": bool(convert), "rotate_z_deg": args.rotate_z,
              "transform": {"scale": scale, "offset": offset, "note": "applied after axis conversion"},
              "objects": len(meshes), "vertices": sum(len(o.data.vertices) for o in meshes), "triangles": fc.triangle_count(meshes),
              "materials": materials, "images": images}
    fc.write_json(out / "preflight-blender.json", report)
    print("FORGE_PREFLIGHT_DONE", report["vertices"], report["triangles"], flush=True)


if __name__ == "__main__":
    main()
