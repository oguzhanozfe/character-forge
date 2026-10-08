"""Mesh measurements for the gates: topology, components/debris, regions, UV texel density, stretch, digits.

Every function measures; none deletes or repairs geometry. Thresholds live in the preset and are PROPOSALS.
"""
from __future__ import annotations

import math
from collections import defaultdict

from . import vecmath as vm
from .obj import Mesh
from .util_stats import median, percentile


# ---------------------------------------------------------------- welding and topology

def weld_map(vertices, tolerance=1e-6):
    """Canonical index per vertex: glTF/FBX exports split vertices at UV/normal seams; weld by position."""
    canonical, result = {}, []
    scale = 1.0 / tolerance
    for index, v in enumerate(vertices):
        if not vm.is_finite_seq(v):
            result.append(index)  # never weld nonfinite points; they are reported separately
            continue
        key = (round(v[0] * scale), round(v[1] * scale), round(v[2] * scale))
        result.append(canonical.setdefault(key, index))
    return result


def polygon_edges(mesh: Mesh, weld=None):
    counts = defaultdict(int)
    for face in mesh.faces:
        ids = [weld[i] for i in face] if weld else list(face)
        for k in range(len(ids)):
            a, b = ids[k], ids[(k + 1) % len(ids)]
            if a != b:
                counts[(a, b) if a < b else (b, a)] += 1
    return counts


def adjacency(mesh: Mesh, weld=None):
    neighbours = defaultdict(set)
    for (a, b) in polygon_edges(mesh, weld):
        neighbours[a].add(b)
        neighbours[b].add(a)
    return neighbours


def components(mesh: Mesh, weld=None):
    """Connected components as sorted lists of (canonical) vertex indices, largest first."""
    weld = weld or weld_map(mesh.vertices)
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for face in mesh.faces:
        ids = [weld[i] for i in face]
        root = find(ids[0])
        for other in ids[1:]:
            r = find(other)
            if r != root:
                parent[r] = root
    groups = defaultdict(list)
    for canonical in {weld[i] for face in mesh.faces for i in face}:
        groups[find(canonical)].append(canonical)
    return sorted((sorted(g) for g in groups.values()), key=len, reverse=True)


def triangle_area(a, b, c):
    return 0.5 * vm.length(vm.cross(vm.sub(b, a), vm.sub(c, a)))


def topology_report(mesh: Mesh):
    weld = weld_map(mesh.vertices)
    edges = polygon_edges(mesh, weld)
    nonfinite = sum(not vm.is_finite_seq(v) for v in mesh.vertices)
    degenerate = []
    for face_index, (a, b, c), _ in mesh.triangles():
        if triangle_area(mesh.vertices[a], mesh.vertices[b], mesh.vertices[c]) < 1e-12:
            degenerate.append(face_index)
    return {"vertices": len(mesh.vertices), "welded_vertices": len(set(weld)), "faces": len(mesh.faces),
            "triangles": mesh.triangle_count(), "nonfinite_vertices": nonfinite,
            "degenerate_triangles": len(degenerate), "degenerate_face_ids_first_20": sorted(set(degenerate))[:20],
            "boundary_edges": sum(1 for c in edges.values() if c == 1),
            "nonmanifold_edges": sum(1 for c in edges.values() if c > 2),
            "self_intersections": "NOT_MEASURED (needs a BVH; review renders)"}


# ---------------------------------------------------------------- regions

REGION_SEGMENTS = [
    ("head", "Head", "HeadTop"), ("neck", "Neck", "Head"),
    ("torso", "Hips", "Spine"), ("torso", "Spine", "Chest"), ("torso", "Chest", "UpperChest"), ("torso", "UpperChest", "Neck"),
]
for _side in ("Left", "Right"):
    s = _side.lower()
    REGION_SEGMENTS += [
        (s + "_shoulder", _side + "Shoulder", _side + "UpperArm"),
        (s + "_upper_arm", _side + "UpperArm", _side + "LowerArm"), (s + "_forearm", _side + "LowerArm", _side + "Hand"),
        (s + "_hand", _side + "Hand", _side + "MiddleProximal"), (s + "_hand", _side + "MiddleProximal", _side + "MiddleTip"),
        (s + "_hand", _side + "IndexProximal", _side + "IndexTip"), (s + "_hand", _side + "LittleProximal", _side + "LittleTip"),
        (s + "_hand", _side + "ThumbProximal", _side + "ThumbTip"),
        (s + "_thigh", _side + "UpperLeg", _side + "LowerLeg"), (s + "_shin", _side + "LowerLeg", _side + "Foot"),
        (s + "_foot", _side + "Foot", _side + "Toes"), (s + "_foot", _side + "Toes", _side + "ToeTip"),
    ]
PROTECTED_REGIONS = ("head", "left_hand", "right_hand", "left_foot", "right_foot")


def classify_point(p, landmarks):
    best, region = float("inf"), "unknown"
    for name, a, b in REGION_SEGMENTS:
        if a in landmarks and b in landmarks:
            d, _ = vm.point_segment_distance(p, landmarks[a], landmarks[b])
            if d < best:
                best, region = d, name
    return region


def component_report(mesh: Mesh, landmarks, height, debris_vertex_fraction=0.005, debris_size_fraction=0.03):
    weld = weld_map(mesh.vertices)
    comps = components(mesh, weld)
    total = sum(len(c) for c in comps) or 1
    rows = []
    for index, comp in enumerate(comps):
        pts = [mesh.vertices[i] for i in comp]
        lo = tuple(min(p[k] for p in pts) for k in range(3))
        hi = tuple(max(p[k] for p in pts) for k in range(3))
        centroid = tuple(sum(p[k] for p in pts) / len(pts) for k in range(3))
        size = vm.distance(lo, hi)
        region = classify_point(centroid, landmarks) if landmarks else "unknown"
        small = len(comp) / total < debris_vertex_fraction and size < debris_size_fraction * height
        status = "main" if index == 0 else ("review" if region in PROTECTED_REGIONS and small else
                                             ("debris_candidate" if small else "part"))
        rows.append({"component": index, "vertices": len(comp), "vertex_fraction": round(len(comp) / total, 6),
                     "bbox_min": [round(x, 5) for x in lo], "bbox_max": [round(x, 5) for x in hi],
                     "size_m": round(size, 5), "region": region, "status": status})
    return rows


def completeness_report(mesh: Mesh, landmarks, height, radius_fraction=0.04):
    """Is there geometry at the head top, both hands/fingertips and both feet?"""
    radius = radius_fraction * height
    probes = {"head_top": "HeadTop", "left_wrist": "LeftHand", "right_wrist": "RightHand",
              "left_fingertips": "LeftMiddleTip", "right_fingertips": "RightMiddleTip",
              "left_foot": "LeftFoot", "right_foot": "RightFoot", "left_toes": "LeftToeTip", "right_toes": "RightToeTip"}
    result = {}
    for label, name in probes.items():
        target = landmarks.get(name)
        result[label] = None if target is None else sum(1 for v in mesh.vertices if vm.distance(v, target) < radius)
    return result


# ---------------------------------------------------------------- UV / texel density

def uv_report(mesh: Mesh, landmarks, texture_size=2048, subpixel_px=1.0, tiny_island_px=16.0):
    by_region = defaultdict(list)
    subpixel = defaultdict(int)
    missing = nonfinite = out_of_range = 0
    island_area = defaultdict(float)
    uv_parent = {}

    def find(x):
        while uv_parent.setdefault(x, x) != x:
            uv_parent[x] = uv_parent[uv_parent[x]]
            x = uv_parent[x]
        return x

    for face_uv in mesh.face_uvs:
        if face_uv:
            root = find(face_uv[0])
            for t in face_uv[1:]:
                r = find(t)
                if r != root:
                    uv_parent[r] = root
    region_cache = {}
    for face_index, (a, b, c), uv in mesh.triangles():
        pa, pb, pc = mesh.vertices[a], mesh.vertices[b], mesh.vertices[c]
        world = triangle_area(pa, pb, pc)
        key = face_index
        if key not in region_cache:
            centroid = tuple((pa[k] + pb[k] + pc[k]) / 3 for k in range(3))
            region_cache[key] = classify_point(centroid, landmarks) if landmarks else "unknown"
        region = region_cache[key]
        if not uv:
            missing += 1
            continue
        ta, tb, tc = (mesh.uvs[i] for i in uv)
        if not all(math.isfinite(x) for t in (ta, tb, tc) for x in t):
            nonfinite += 1
            continue
        if any(x < -1e-4 or x > 1 + 1e-4 for t in (ta, tb, tc) for x in t):
            out_of_range += 1
        uv_px = abs((tb[0] - ta[0]) * (tc[1] - ta[1]) - (tc[0] - ta[0]) * (tb[1] - ta[1])) * 0.5 * texture_size ** 2
        island_area[find(uv[0])] += uv_px
        if uv_px < subpixel_px:
            subpixel[region] += 1
        if world > 1e-10:
            by_region[region].append(math.sqrt(uv_px / world))
    densities = {r: {"median_px_per_m": round(median(v), 1), "p10_px_per_m": round(percentile(v, 10), 1), "triangles": len(v)}
                 for r, v in sorted(by_region.items())}
    body = [d for r, v in by_region.items() if r != "head" for d in v]
    head = by_region.get("head", [])
    return {"texture_size": texture_size, "faces_missing_uv": missing, "nonfinite_uv_triangles": nonfinite,
            "triangles_outside_0_1": out_of_range, "subpixel_triangles_by_region": dict(subpixel),
            "subpixel_triangles_head": subpixel.get("head", 0), "uv_islands": len(island_area),
            "tiny_uv_islands": sum(1 for a in island_area.values() if a < tiny_island_px),
            "density_by_region": densities,
            "head_median_px_per_m": round(median(head), 1) if head else 0.0,
            "body_median_px_per_m": round(median(body), 1) if body else 0.0,
            "head_to_body_density_ratio": round(median(head) / median(body), 3) if head and body and median(body) > 0 else 0.0}


# ---------------------------------------------------------------- deformation

def unique_edges(mesh: Mesh):
    return list(polygon_edges(mesh).keys())


def edge_stretch(rest, posed, edges, min_rest_length=1e-4, red_flag=3.0, worst=12):
    samples, ignored = [], 0
    for a, b in edges:
        old = vm.distance(rest[a], rest[b])
        if old < min_rest_length:
            ignored += 1
            continue
        samples.append((vm.distance(posed[a], posed[b]) / old, a, b))
    if not samples:
        return {"edges": 0, "max_ratio": 1.0, "min_ratio": 1.0, "over_red_flag": 0, "worst": []}
    samples.sort(reverse=True)
    return {"edges": len(samples), "ignored_short_edges": ignored, "max_ratio": round(samples[0][0], 4),
            "min_ratio": round(min(s[0] for s in samples), 4), "red_flag_ratio": red_flag,
            "over_red_flag": sum(1 for s in samples if s[0] > red_flag),
            "compressed_below_inverse": sum(1 for s in samples if s[0] < 1.0 / red_flag),
            "worst": [{"ratio": round(r, 4), "vertices": [a, b]} for r, a, b in samples[:worst]]}


def all_finite(points):
    return all(vm.is_finite_seq(p) for p in points)


# ---------------------------------------------------------------- hands

def digit_separation(vertices, neighbours, wrist, tip, slab=(0.62, 1.2), radius_fraction=0.7, min_vertices=3):
    """Count separate digit cross-sections in the distal finger zone of one hand.

    Works on connected meshes: vertices beyond the knuckles are induced into a subgraph whose connected
    components are the digits. Fused fingers produce fewer components. The thumb is not in this slab.
    """
    d = vm.normalize(vm.sub(tip, wrist))
    hand = vm.distance(wrist, tip)
    selected = set()
    for index, v in enumerate(vertices):
        rel = vm.sub(v, wrist)
        t = vm.dot(rel, d) / hand
        if slab[0] <= t <= slab[1]:
            radial = vm.length(vm.sub(rel, vm.mul(d, vm.dot(rel, d))))
            if radial < radius_fraction * hand:
                selected.add(index)
    seen, sizes = set(), []
    for start in selected:
        if start in seen:
            continue
        stack, size = [start], 0
        seen.add(start)
        while stack:
            current = stack.pop()
            size += 1
            for n in neighbours.get(current, ()):
                if n in selected and n not in seen:
                    seen.add(n)
                    stack.append(n)
        sizes.append(size)
    digits = [s for s in sizes if s >= min_vertices]
    return {"distal_digit_sections": len(digits), "section_vertex_counts": sorted(digits, reverse=True),
            "slab_vertices": len(selected)}


def seam_gap(rest_a, posed_a, rest_b, posed_b):
    """Largest growth of nearest-neighbour distance from boundary set A to set B between rest and pose."""
    if not rest_a or not rest_b:
        return None
    worst = 0.0
    for ra, pa in zip(rest_a, posed_a):
        rest_d = min(vm.distance(ra, rb) for rb in rest_b)
        pose_d = min(vm.distance(pa, pb) for pb in posed_b)
        worst = max(worst, pose_d - rest_d)
    return worst
