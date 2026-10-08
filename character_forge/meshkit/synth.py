"""Synthetic humanoid fixtures: an A-pose body of elliptical tubes with five-digit hands, UVs and weights.

Used by fake mode (in place of a reconstruction) and by the tests (fixtures are generated, never committed).
The body is deliberately simple; it exercises every gate, including deliberate defects on request.
"""
from __future__ import annotations

import math
import random

from . import vecmath as vm
from .obj import Mesh
from .skeleton import FINGERS, SEGMENTS, SIDES, Proportions, Skeleton, hand_frame, template_landmarks
from .skinning import limit_and_normalize


def proportions_from_seed(seed: int) -> Proportions:
    rng = random.Random(seed)
    return Proportions(height=round(rng.uniform(1.55, 1.95), 3), shoulder_half=rng.uniform(0.115, 0.145),
                       hip_half=rng.uniform(0.048, 0.062), arm_angle=rng.uniform(38, 52), arm_length=rng.uniform(0.42, 0.46),
                       leg_spread=rng.uniform(0.0, 0.03), head_scale=rng.uniform(0.92, 1.1), hunch=rng.uniform(0.0, 0.05),
                       hand_scale=rng.uniform(0.95, 1.05))


class _Builder:
    def __init__(self, sides=10):
        self.mesh = Mesh()
        self.sides = sides

    def tube(self, group, points, radii, tile, material="Body", x_axis_hint=None, rings_per_segment=3, caps=True):
        """points: chain centres; radii: [(rx, ry)] per point; tile: (u0, v0, w, h) UV rectangle."""
        centres, rads = [], []
        for i in range(len(points) - 1):
            for k in range(rings_per_segment):
                t = k / rings_per_segment
                centres.append(vm.lerp(points[i], points[i + 1], t))
                rads.append((radii[i][0] + (radii[i + 1][0] - radii[i][0]) * t, radii[i][1] + (radii[i + 1][1] - radii[i][1]) * t))
        centres.append(points[-1])
        rads.append(radii[-1])
        total = sum(vm.distance(centres[i], centres[i + 1]) for i in range(len(centres) - 1)) or 1.0
        mesh = self.mesh
        ring_ids, ring_uvs, run = [], [], 0.0
        for index, centre in enumerate(centres):
            if index > 0:
                run += vm.distance(centres[index - 1], centre)
            ahead = centres[min(index + 1, len(centres) - 1)]
            behind = centres[max(index - 1, 0)]
            direction = vm.normalize(vm.sub(ahead, behind))
            hint = x_axis_hint or ((1.0, 0.0, 0.0) if abs(direction[0]) < 0.9 else (0.0, 1.0, 0.0))
            ax = vm.sub(hint, vm.mul(direction, vm.dot(hint, direction)))
            ax = vm.normalize(ax)
            ay = vm.cross(direction, ax)
            ids, uvs = [], []
            for s in range(self.sides + 1):  # seam column duplicated in UV space only
                angle = 2 * math.pi * s / self.sides
                if s < self.sides:
                    rx, ry = rads[index]
                    p = vm.add(centre, vm.add(vm.mul(ax, math.cos(angle) * rx), vm.mul(ay, math.sin(angle) * ry)))
                    mesh.vertices.append(p)
                    ids.append(len(mesh.vertices) - 1)
                mesh.uvs.append((tile[0] + tile[2] * (0.04 + 0.92 * s / self.sides), tile[1] + tile[3] * (0.04 + 0.92 * run / total)))
                uvs.append(len(mesh.uvs) - 1)
            ring_ids.append(ids)
            ring_uvs.append(uvs)
        for r in range(len(ring_ids) - 1):
            a, b = ring_ids[r], ring_ids[r + 1]
            ta, tb = ring_uvs[r], ring_uvs[r + 1]
            for s in range(self.sides):
                s2 = (s + 1) % self.sides
                mesh.faces.append((a[s], a[s2], b[s2], b[s]))
                mesh.face_uvs.append((ta[s], ta[s + 1], tb[s + 1], tb[s]))
                mesh.face_groups.append(group)
                mesh.face_materials.append(material)
        if caps:
            for ids, centre, uvs, flip in ((ring_ids[0], centres[0], ring_uvs[0], True), (ring_ids[-1], centres[-1], ring_uvs[-1], False)):
                mesh.vertices.append(centre)
                c = len(mesh.vertices) - 1
                mesh.uvs.append((tile[0] + tile[2] * 0.5, tile[1] + tile[3] * (0.01 if flip else 0.99)))
                cu = len(mesh.uvs) - 1
                for s in range(self.sides):
                    s2 = (s + 1) % self.sides
                    face = (ids[s2], ids[s], c) if flip else (ids[s], ids[s2], c)
                    fuv = (uvs[s + 1], uvs[s], cu) if flip else (uvs[s], uvs[s + 1], cu)
                    mesh.faces.append(face)
                    mesh.face_uvs.append(fuv)
                    mesh.face_groups.append(group)
                    mesh.face_materials.append(material)


def synthetic_humanoid(proportions: Proportions | None = None, seed: int | None = None, debris=False,
                       fused_fingers=False, tiny_head_uv=False, sides=10):
    """Return (mesh, landmarks). Groups: head, torso, <side>_arm, <side>_<finger>, <side>_leg, <side>_foot."""
    p = proportions or (proportions_from_seed(seed) if seed is not None else Proportions())
    h = p.height
    lm = template_landmarks(p)
    b = _Builder(sides)
    hs = p.head_scale
    head_tile = (0.0, 0.5, 0.01, 0.01) if tiny_head_uv else (0.0, 0.5, 0.5, 0.5)
    neck, head, top = lm["Neck"], lm["Head"], lm["HeadTop"]
    b.tube("torso", [(0, lm["Hips"][1], 0.465 * h), lm["Hips"], lm["Spine"], lm["Chest"], lm["UpperChest"], vm.lerp(lm["UpperChest"], neck, 0.6)],
           [(0.085 * h, 0.06 * h), (0.095 * h, 0.062 * h), (0.083 * h, 0.055 * h), (0.098 * h, 0.064 * h), (0.105 * h, 0.066 * h), (0.06 * h, 0.05 * h)],
           (0.5, 0.5, 0.5, 0.5), material="Body")
    b.tube("head", [vm.lerp(lm["UpperChest"], neck, 0.5), neck, head, vm.lerp(head, top, 0.45), vm.lerp(head, top, 0.97)],
           [(0.034 * h, 0.034 * h), (0.036 * h, 0.036 * h), (0.05 * h * hs, 0.056 * h * hs), (0.063 * h * hs, 0.07 * h * hs), (0.03 * h * hs, 0.03 * h * hs)],
           head_tile, material="Head")
    finger_tiles = [(0.5 + (i % 5) * 0.1, 0.13 + (i // 5) * 0.18, 0.1, 0.17) for i in range(10)]
    for si, side in enumerate(SIDES):
        s = side.lower()
        wrist, middle_tip = lm[side + "Hand"], lm[side + "MiddleTip"]
        d, n, w = hand_frame(side, wrist, middle_tip)
        knuckles = lm[side + "MiddleProximal"]
        b.tube(s + "_arm", [vm.lerp(lm[side + "Shoulder"], lm[side + "UpperArm"], 0.55), lm[side + "UpperArm"], lm[side + "LowerArm"], wrist, knuckles],
               [(0.042 * h, 0.042 * h), (0.045 * h, 0.045 * h), (0.036 * h, 0.036 * h), (0.022 * h, 0.026 * h), (0.034 * h, 0.012 * h)],
               (0.125 * si, 0.0, 0.125, 0.5), x_axis_hint=w)
        fingers = FINGERS[1:] if not fused_fingers else ()
        for fi, finger in enumerate(FINGERS):
            if fused_fingers and finger != "Thumb":
                continue
            chain = [lm[side + finger + seg] for seg in SEGMENTS] + [lm[side + finger + "Tip"]]
            r = 0.0075 * h * p.hand_scale * (1.15 if finger == "Thumb" else 1.0)
            b.tube(s + "_" + finger.lower(), chain, [(r, r), (r * 0.9, r * 0.9), (r * 0.8, r * 0.8), (r * 0.55, r * 0.55)],
                   finger_tiles[si * 5 + fi], material="Body", rings_per_segment=2)
        del fingers
        if fused_fingers:
            base = lm[side + "MiddleProximal"]
            b.tube(s + "_mitten", [base, lm[side + "MiddleIntermediate"], lm[side + "MiddleDistal"], lm[side + "MiddleTip"]],
                   [(0.035 * h, 0.009 * h)] * 3 + [(0.02 * h, 0.006 * h)], finger_tiles[si * 5 + 1], x_axis_hint=w, rings_per_segment=2)
        b.tube(s + "_leg", [vm.add(lm[side + "UpperLeg"], (0, 0, 0.02 * h)), lm[side + "UpperLeg"], lm[side + "LowerLeg"], lm[side + "Foot"]],
               [(0.07 * h, 0.07 * h), (0.072 * h, 0.072 * h), (0.048 * h, 0.048 * h), (0.032 * h, 0.032 * h)],
               (0.25 + 0.125 * si, 0.0, 0.125, 0.5))
        b.tube(s + "_foot", [vm.add(lm[side + "Foot"], (0, 0.03 * h, 0)), lm[side + "Toes"], lm[side + "ToeTip"]],
               [(0.03 * h, 0.022 * h), (0.034 * h, 0.014 * h), (0.025 * h, 0.01 * h)],
               (0.5 + 0.125 * si, 0.0, 0.125, 0.125), x_axis_hint=(1.0, 0.0, 0.0))
    if debris:
        # A floating fragment beside the upper arm: outside protected regions, small -> debris candidate.
        centre = vm.add(lm["LeftUpperArm"], (0.02 * h, 0.08 * h, 0.05 * h))
        b.tube("fragment", [centre, vm.add(centre, (0.0, 0.0, 0.01 * h))], [(0.004 * h, 0.004 * h)] * 2,
               (0.9, 0.9, 0.05, 0.05), rings_per_segment=1)
    return b.mesh, lm


# ---------------------------------------------------------------- synthetic weights

def _candidates(group, skeleton: Skeleton):
    names = set(skeleton.bones)
    if group in ("torso",):
        c = ["Hips", "Spine", "Chest", "UpperChest", "Neck", "LeftShoulder", "RightShoulder", "LeftUpperLeg", "RightUpperLeg"]
    elif group == "head":
        c = ["Neck", "Head", "UpperChest"]
    else:
        side = "Left" if group.startswith("left") else "Right"
        part = group.split("_", 1)[1] if "_" in group else group
        if part == "arm":
            c = [side + x for x in ("Shoulder", "UpperArm", "LowerArm", "ForearmTwist", "Hand")]
        elif part == "leg":
            c = ["Hips", side + "UpperLeg", side + "LowerLeg", side + "Foot"]
        elif part == "foot":
            c = [side + "LowerLeg", side + "Foot", side + "Toes"]
        elif part == "mitten":
            c = [side + "Hand"] + [side + f + s for f in ("Index", "Middle", "Ring", "Little") for s in SEGMENTS]
        elif part.capitalize() in FINGERS:
            f = part.capitalize()
            c = [side + "Hand"] + [side + f + s for s in SEGMENTS]
        else:
            c = list(names)
    return [n for n in c if n in names]


def synthetic_weights(mesh: Mesh, skeleton: Skeleton, falloff=4.0, limit=4):
    """Inverse-distance weights to bone segments, restricted to the part's anatomical candidates."""
    groups = mesh.vertex_groups()
    cache = {}
    rows = []
    for v, group in zip(mesh.vertices, groups):
        if group not in cache:
            cache[group] = _candidates(group or "", skeleton)
        scored = []
        for name in cache[group]:
            bone = skeleton.bones[name]
            d, _ = vm.point_segment_distance(v, bone.head, bone.tail)
            scored.append((d, name))
        scored.sort()
        nearest = scored[0][0]
        kept = [(name, 1.0 / (d + 0.004) ** falloff) for d, name in scored if d <= nearest * 1.8 + 0.01]
        rows.append(limit_and_normalize(kept, limit))
    return rows
