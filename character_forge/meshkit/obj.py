"""Wavefront OBJ read/write for the interchange mesh (positions, UVs, faces, groups, materials)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Mesh:
    vertices: list = field(default_factory=list)       # [(x, y, z)]
    uvs: list = field(default_factory=list)            # [(u, v)]
    faces: list = field(default_factory=list)          # [(i0, i1, i2, ...)] vertex indices
    face_uvs: list = field(default_factory=list)       # [(t0, t1, ...)] or None per face
    face_groups: list = field(default_factory=list)    # group/object name per face
    face_materials: list = field(default_factory=list) # material name per face

    def triangles(self):
        """Fan-triangulate. Yields (face_index, (a, b, c), (ta, tb, tc) or None)."""
        for index, face in enumerate(self.faces):
            uv = self.face_uvs[index] if index < len(self.face_uvs) else None
            for k in range(1, len(face) - 1):
                yield index, (face[0], face[k], face[k + 1]), ((uv[0], uv[k], uv[k + 1]) if uv else None)

    def triangle_count(self):
        return sum(len(face) - 2 for face in self.faces)

    def bounds(self):
        xs, ys, zs = zip(*self.vertices)
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def vertex_groups(self):
        """Group name per vertex (first face that uses it wins)."""
        result = [None] * len(self.vertices)
        for face, group in zip(self.faces, self.face_groups):
            for index in face:
                if result[index] is None:
                    result[index] = group
        return result

    def copy(self):
        return Mesh(list(self.vertices), list(self.uvs), list(self.faces), list(self.face_uvs),
                    list(self.face_groups), list(self.face_materials))


def read_obj(path) -> Mesh:
    mesh = Mesh()
    group = "default"
    material = "default"
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            parts = line.split()
            if not parts or parts[0].startswith("#"):
                continue
            key = parts[0]
            if key == "v":
                mesh.vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif key == "vt":
                mesh.uvs.append((float(parts[1]), float(parts[2])))
            elif key in ("o", "g"):
                group = " ".join(parts[1:]) or "default"
            elif key == "usemtl":
                material = " ".join(parts[1:]) or "default"
            elif key == "f":
                vertex_ids, uv_ids = [], []
                for token in parts[1:]:
                    fields = token.split("/")
                    v = int(fields[0])
                    vertex_ids.append(v - 1 if v > 0 else len(mesh.vertices) + v)
                    if len(fields) > 1 and fields[1]:
                        t = int(fields[1])
                        uv_ids.append(t - 1 if t > 0 else len(mesh.uvs) + t)
                if len(vertex_ids) < 3:
                    continue
                mesh.faces.append(tuple(vertex_ids))
                mesh.face_uvs.append(tuple(uv_ids) if len(uv_ids) == len(vertex_ids) else None)
                mesh.face_groups.append(group)
                mesh.face_materials.append(material)
    return mesh


def write_obj(mesh: Mesh, path, header: str = "character-forge interchange mesh") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# " + header, "# units: metres, Z up, character faces -Y"]
    lines += ["v %.6f %.6f %.6f" % v for v in mesh.vertices]
    lines += ["vt %.6f %.6f" % t for t in mesh.uvs]
    group = material = None
    for index, face in enumerate(mesh.faces):
        g = mesh.face_groups[index] if index < len(mesh.face_groups) else "default"
        m = mesh.face_materials[index] if index < len(mesh.face_materials) else "default"
        if g != group:
            lines.append("o " + g)
            group = g
        if m != material:
            lines.append("usemtl " + m)
            material = m
        uv = mesh.face_uvs[index] if index < len(mesh.face_uvs) else None
        if uv:
            lines.append("f " + " ".join("%d/%d" % (v + 1, t + 1) for v, t in zip(face, uv)))
        else:
            lines.append("f " + " ".join(str(v + 1) for v in face))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path
