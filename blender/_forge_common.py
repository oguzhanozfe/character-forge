"""Shared helpers for character-forge Blender scripts (run inside Blender's Python).

All scripts are invoked as:
  blender --background --factory-startup --python-exit-code 1 --python <script> -- <args>
They take explicit input/output paths, write only inside their output directory and never touch machine config.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy


def parse(description, configure):
    parser = argparse.ArgumentParser(description=description)
    configure(parser)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(argv)


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_any(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(path))
    elif suffix in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == ".obj":
        with open(path, encoding="utf-8", errors="replace") as stream:
            head = stream.read(400)
        if "Z up" in head:  # character-forge interchange OBJ: already Blender coordinates
            bpy.ops.wm.obj_import(filepath=str(path), forward_axis="Y", up_axis="Z")
        else:
            bpy.ops.wm.obj_import(filepath=str(path), forward_axis="NEGATIVE_Z", up_axis="Y")
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    else:
        raise ValueError("Unsupported source format: " + suffix)


def mesh_objects():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def bake_transforms(objects):
    """Apply each object's world transform into its vertices and clear parenting."""
    for obj in objects:
        matrix = obj.matrix_world.copy()
        obj.parent = None
        obj.data.transform(matrix)
        obj.matrix_world.identity()
        obj.data.update()


def join(objects, name):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    if len(objects) > 1:
        bpy.ops.object.join()
    result = bpy.context.view_layer.objects.active
    result.name = name
    result.data.name = name
    return result


def write_obj(objects, path, header="character-forge interchange (Blender)"):
    """OBJ writer that preserves Blender vertex order exactly (Blender's exporter may reorder/split)."""
    lines = ["# " + header, "# units: metres, Z up, character faces -Y"]
    offset = 0
    uv_offset = 0
    for obj in objects:
        mesh = obj.data
        matrix = obj.matrix_world
        for v in mesh.vertices:
            co = matrix @ v.co
            lines.append("v %.6f %.6f %.6f" % (co.x, co.y, co.z))
        uv_layer = mesh.uv_layers.active.data if mesh.uv_layers.active else None
        if uv_layer:
            for loop in mesh.loops:
                uv = uv_layer[loop.index].uv
                lines.append("vt %.6f %.6f" % (uv.x, uv.y))
        lines.append("o " + obj.name)
        material = None
        for poly in mesh.polygons:
            name = mesh.materials[poly.material_index].name if mesh.materials and poly.material_index < len(mesh.materials) and mesh.materials[poly.material_index] else "default"
            if name != material:
                lines.append("usemtl " + name)
                material = name
            if uv_layer:
                lines.append("f " + " ".join("%d/%d" % (mesh.loops[li].vertex_index + 1 + offset, li + 1 + uv_offset) for li in poly.loop_indices))
            else:
                lines.append("f " + " ".join(str(vi + 1 + offset) for vi in poly.vertices))
        offset += len(mesh.vertices)
        uv_offset += len(mesh.loops) if uv_layer else 0
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return Path(path)


def bounds(objects):
    xs, ys, zs = [], [], []
    for obj in objects:
        for v in obj.data.vertices:
            co = obj.matrix_world @ v.co
            xs.append(co.x)
            ys.append(co.y)
            zs.append(co.z)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def triangle_count(objects):
    return sum(len(p.vertices) - 2 for o in objects for p in o.data.polygons)


def neutral_cycles(scene, samples=8, resolution=(384, 512)):
    """CPU-only Cycles so review renders never compete with GPU jobs."""
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    try:
        scene.cycles.use_denoising = False
    except AttributeError:
        pass
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    world = bpy.data.worlds.new("ForgeNeutral")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.14, 0.15, 0.17, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.6
    scene.world = world


def add_lights(scene, height):
    from mathutils import Vector
    for position, power in (((2, -4, 4), 500), ((-3, -1, 2), 200), ((1, 3, 4), 350)):
        data = bpy.data.lights.new("ForgeLight", "AREA")
        data.energy, data.size = power, 3
        obj = bpy.data.objects.new("ForgeLight", data)
        scene.collection.objects.link(obj)
        obj.location = position
        obj.rotation_euler = (Vector((0, 0, height / 2)) - obj.location).to_track_quat("-Z", "Y").to_euler()


def ortho_camera(scene):
    data = bpy.data.cameras.new("ForgeCamera")
    data.type = "ORTHO"
    camera = bpy.data.objects.new("ForgeCamera", data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    return camera


def aim(camera, target, offset, span):
    from mathutils import Vector
    camera.location = Vector(target) + Vector(offset)
    camera.rotation_euler = (-Vector(offset)).to_track_quat("-Z", "Y").to_euler()
    camera.data.ortho_scale = span


def finite(values):
    return all(math.isfinite(v) for v in values)
