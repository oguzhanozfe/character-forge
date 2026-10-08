"""Low mesh, UV and bake: join the static source into one body, decimate to the triangle budget, keep or create UVs
with head texel priority, bake BaseColor/Normal/roughness from the original source, write runtime textures.

  blender --background --factory-startup --python-exit-code 1 --python lowmesh.py -- \
      --source static.blend --output-dir <run> --id demo --triangles 66000 --texture-size 2048 [--no-bake] [--reunwrap]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _forge_common as fc  # noqa: E402

import bmesh  # noqa: E402
import bpy  # noqa: E402
import numpy as np  # noqa: E402


def configure(p):
    p.add_argument("--source", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--triangles", type=int, required=True)
    p.add_argument("--texture-size", type=int, default=2048)
    p.add_argument("--head-priority", type=float, default=1.8, help="relative texel density for the head region")
    p.add_argument("--no-bake", action="store_true")
    p.add_argument("--reunwrap", action="store_true")


def uv_ok(obj):
    if not obj.data.uv_layers:
        return False
    data = obj.data.uv_layers.active.data
    zero = 0
    for poly in obj.data.polygons:
        uvs = [data[i].uv for i in poly.loop_indices]
        if len(uvs) >= 3:
            area = abs((uvs[1].x - uvs[0].x) * (uvs[2].y - uvs[0].y) - (uvs[2].x - uvs[0].x) * (uvs[1].y - uvs[0].y))
            zero += area < 1e-12
    return zero < 0.01 * max(1, len(obj.data.polygons))


def unwrap_with_head_priority(obj, height, priority):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.003)
    bpy.ops.uv.average_islands_scale()
    bm = bmesh.from_edit_mesh(obj.data)
    uv = bm.loops.layers.uv.active
    head_faces = [f for f in bm.faces if f.calc_center_median().z > 0.86 * height]
    # Scale every island touching the head about its own centre; pack_islands then keeps relative sizes.
    islands, seen = [], set()
    for face in head_faces:
        if face.index in seen:
            continue
        stack, island = [face], []
        seen.add(face.index)
        while stack:
            f = stack.pop()
            island.append(f)
            for loop in f.loops:
                for other in loop.edge.link_faces:
                    if other.index not in seen and not loop.edge.seam and other.calc_center_median().z > 0.80 * height:
                        seen.add(other.index)
                        stack.append(other)
        islands.append(island)
    for island in islands:
        loops = [l for f in island for l in f.loops]
        cx = sum(l[uv].uv.x for l in loops) / len(loops)
        cy = sum(l[uv].uv.y for l in loops) / len(loops)
        for l in loops:
            l[uv].uv.x = cx + (l[uv].uv.x - cx) * priority
            l[uv].uv.y = cy + (l[uv].uv.y - cy) * priority
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.uv.pack_islands(rotate=True, margin=0.004)
    bpy.ops.object.mode_set(mode="OBJECT")
    return len(head_faces)


def new_image(name, size, colour, non_color=False):
    image = bpy.data.images.new(name, size, size, alpha=True)
    image.generated_color = colour
    if non_color:
        image.colorspace_settings.name = "Non-Color"
    return image


def bake(low, high_objects, image, kind, extrusion):
    material = low.data.materials[0]
    nodes = material.node_tree.nodes
    node = nodes.new("ShaderNodeTexImage")
    node.image = image
    nodes.active = node
    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    for obj in high_objects:
        obj.hide_render = False
        obj.select_set(True)
    low.select_set(True)
    bpy.context.view_layer.objects.active = low
    scene = bpy.context.scene
    scene.render.bake.use_selected_to_active = True
    scene.render.bake.cage_extrusion = extrusion
    scene.render.bake.margin = 8
    if kind == "DIFFUSE":
        scene.render.bake.use_pass_direct = False
        scene.render.bake.use_pass_indirect = False
        scene.render.bake.use_pass_color = True
    bpy.ops.object.bake(type=kind)
    nodes.remove(node)


def main():
    args = fc.parse(__doc__, configure)
    out = Path(args.output_dir).resolve()
    (out / "Textures").mkdir(parents=True, exist_ok=True)
    fc.reset()
    fc.import_any(args.source)
    sources = fc.mesh_objects()
    lo, hi = fc.bounds(sources)
    height = hi[2] - lo[2]
    # Keep the original as the bake source; build the low mesh from a joined copy.
    copies = []
    for obj in sources:
        dup = obj.copy()
        dup.data = obj.data.copy()
        bpy.context.scene.collection.objects.link(dup)
        copies.append(dup)
    low = fc.join(copies, args.id + "_Body")
    source_tris = fc.triangle_count([low])
    decimated = False
    if source_tris > args.triangles:
        modifier = low.modifiers.new("ForgeDecimate", "DECIMATE")
        modifier.ratio = args.triangles / source_tris * 0.98
        bpy.context.view_layer.objects.active = low
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        decimated = True
    reunwrapped = args.reunwrap or not uv_ok(low)
    head_faces = unwrap_with_head_priority(low, height, args.head_priority) if reunwrapped else 0
    low.data.materials.clear()
    material = bpy.data.materials.new(args.id + "_Body")
    material.use_nodes = True
    low.data.materials.append(material)
    size = args.texture_size
    textures = {}
    has_source_images = any(i.type == "IMAGE" and i.size[0] > 0 for i in bpy.data.images)
    base = new_image(args.id + "_BaseColor", size, (0.5, 0.46, 0.41, 1.0))
    normal = new_image(args.id + "_Normal", size, (0.5, 0.5, 1.0, 1.0), non_color=True)
    rough = new_image(args.id + "_Roughness", size, (0.7, 0.7, 0.7, 1.0), non_color=True)
    baked = []
    if not args.no_bake:
        fc.neutral_cycles(bpy.context.scene, samples=1, resolution=(64, 64))
        extrusion = 0.01 * height
        for obj in sources:
            obj.hide_render = False
        if has_source_images or reunwrapped or decimated:
            bake(low, sources, base, "DIFFUSE", extrusion)
            baked.append("BaseColor")
            bake(low, sources, rough, "ROUGHNESS", extrusion)
            baked.append("Roughness")
        if decimated:
            bake(low, sources, normal, "NORMAL", extrusion)
            baked.append("Normal")
    # MetallicSmoothness for URP/Standard: R = metallic (0 for skin/cloth), A = 1 - roughness.
    pixels = np.empty(size * size * 4, dtype=np.float32)
    rough.pixels.foreach_get(pixels)
    smooth = 1.0 - pixels.reshape(-1, 4)[:, 0]
    mask = np.zeros((size * size, 4), dtype=np.float32)
    mask[:, 3] = np.clip(smooth, 0.0, 1.0)
    metal = new_image(args.id + "_MetallicSmoothness", size, (0, 0, 0, 0.3), non_color=True)
    metal.pixels.foreach_set(mask.ravel())
    for image, channel in ((base, "BaseColor"), (normal, "Normal"), (metal, "MetallicSmoothness")):
        target = out / "Textures" / ("%s_%s.png" % (args.id, channel))
        image.filepath_raw = str(target)
        image.file_format = "PNG"
        image.save()
        textures[channel] = target.name
    # Wire the runtime textures into the low material for preview in Blender.
    nodes, links = material.node_tree.nodes, material.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = base
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    for obj in sources:
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.images.remove(rough)
    fc.write_obj([low], out / "low.obj", header="low mesh %s" % args.id)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "low.blend"))
    report = {"mode": "real", "blender": bpy.app.version_string, "source_triangles": source_tris,
              "triangles": fc.triangle_count([low]), "decimated": decimated, "reunwrapped": reunwrapped,
              "head_faces_prioritized": head_faces, "baked": baked, "textures": textures, "texture_size": size,
              "note": "metallic forced to 0 (organic/cloth default); paint metal masks explicitly if needed"}
    fc.write_json(out / "lowmesh-blender.json", report)
    print("FORGE_LOWMESH_DONE", report["triangles"], baked, flush=True)


if __name__ == "__main__":
    main()
