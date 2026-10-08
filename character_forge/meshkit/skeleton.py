"""Humanoid bone contract, landmark template/estimation and skeleton construction.

Bone names follow Unity's HumanBodyBones so the Unity package can map them without a lookup table.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import vecmath as vm
from .util_stats import percentile

SIDES = ("Left", "Right")
FINGERS = ("Thumb", "Index", "Middle", "Ring", "Little")
SEGMENTS = ("Proximal", "Intermediate", "Distal")

TORSO = ["Hips", "Spine", "Chest", "UpperChest", "Neck", "Head"]
ARM = ["Shoulder", "UpperArm", "LowerArm", "Hand"]
LEG = ["UpperLeg", "LowerLeg", "Foot", "Toes"]

HUMAN_BONES = list(TORSO)
for _side in SIDES:
    HUMAN_BONES += [_side + part for part in ARM]
    HUMAN_BONES += [_side + part for part in LEG]
    HUMAN_BONES += [_side + finger + segment for finger in FINGERS for segment in SEGMENTS]
HELPER_BONES = [side + "ForearmTwist" for side in SIDES]
FINGER_BONES = [b for b in HUMAN_BONES if any(f in b for f in FINGERS)]
# Unity's minimum Humanoid requirement; presets may require more (the zombie preset requires all 52).
UNITY_REQUIRED = ["Hips", "Spine", "Head"] + [s + p for s in SIDES for p in ("UpperArm", "LowerArm", "Hand", "UpperLeg", "LowerLeg", "Foot")]


def parent_of(name: str):
    if name == "Hips":
        return None
    if name in TORSO:
        return TORSO[TORSO.index(name) - 1]
    side = "Left" if name.startswith("Left") else "Right"
    part = name[len(side):]
    if part == "Shoulder":
        return "UpperChest"
    if part in ARM:
        return side + ARM[ARM.index(part) - 1]
    if part == "ForearmTwist":
        return side + "LowerArm"
    if part == "UpperLeg":
        return "Hips"
    if part in LEG:
        return side + LEG[LEG.index(part) - 1]
    for finger in FINGERS:
        if part.startswith(finger):
            segment = part[len(finger):]
            return side + "Hand" if segment == "Proximal" else side + finger + SEGMENTS[SEGMENTS.index(segment) - 1]
    raise KeyError(name)


def tail_landmark(name: str) -> str:
    if name in TORSO:
        return "HeadTop" if name == "Head" else TORSO[TORSO.index(name) + 1]
    side = "Left" if name.startswith("Left") else "Right"
    part = name[len(side):]
    if part == "Hand":
        return side + "MiddleProximal"
    if part == "ForearmTwist":
        return side + "Hand"
    if part in ARM:
        return side + ARM[ARM.index(part) + 1]
    if part == "Toes":
        return side + "ToeTip"
    if part in LEG:
        return side + LEG[LEG.index(part) + 1]
    for finger in FINGERS:
        if part.startswith(finger):
            segment = part[len(finger):]
            return side + finger + ("Tip" if segment == "Distal" else SEGMENTS[SEGMENTS.index(segment) + 1])
    raise KeyError(name)


def required_landmarks():
    names = set(HUMAN_BONES) | {"HeadTop"}
    for side in SIDES:
        names |= {side + "ToeTip"} | {side + finger + "Tip" for finger in FINGERS}
    return sorted(names)


# ---------------------------------------------------------------- landmark template

@dataclass
class Proportions:
    height: float = 1.78
    shoulder_half: float = 0.13      # x of shoulder joint, fraction of height
    hip_half: float = 0.055          # x of hip joint, fraction of height
    arm_angle: float = 45.0          # A-pose degrees below horizontal
    arm_length: float = 0.44         # shoulder joint to fingertip, fraction of height
    leg_spread: float = 0.0          # extra ankle x, fraction of height
    head_scale: float = 1.0
    hunch: float = 0.0               # forward offset of upper torso, fraction of height
    hand_scale: float = 1.0


def hand_frame(side, wrist, tip):
    d = vm.normalize(vm.sub(tip, wrist))
    n = vm.cross(d, (0.0, 1.0, 0.0))
    n = vm.mul(vm.normalize(n), -1.0 if side == "Left" else 1.0)  # palm normal points toward the body/down
    w = vm.sub((0.0, 1.0, 0.0), vm.mul(d, d[1]))                  # spread axis: front(-Y) to back(+Y)
    return d, n, vm.normalize(w)


def finger_landmarks(side, wrist, tip):
    """Template knuckle/segment positions for five digits from a wrist and middle fingertip."""
    d, n, w = hand_frame(side, wrist, tip)
    hand = vm.distance(wrist, tip)
    out = {}
    lengths = {"Index": (0.21, 0.13, 0.11), "Middle": (0.23, 0.15, 0.12), "Ring": (0.21, 0.14, 0.11), "Little": (0.17, 0.11, 0.09)}
    spread = {"Index": -1.5, "Middle": -0.5, "Ring": 0.5, "Little": 1.5}
    for finger, lens in lengths.items():
        knuckle_reach = 0.50 if finger == "Middle" else (0.48 if finger in ("Index", "Ring") else 0.45)
        if finger == "Middle":
            # The middle fingertip is the measured tip; scale segments to land on it exactly.
            total = sum(lens)
            lens = tuple(l * (1 - knuckle_reach) / total for l in lens)
        base = vm.add(vm.add(wrist, vm.mul(d, hand * knuckle_reach)), vm.mul(w, spread[finger] * 0.085 * hand))
        direction = vm.normalize(vm.add(d, vm.mul(w, spread[finger] * 0.06)))
        point = base
        for segment, l in zip(SEGMENTS + ("Tip",), (0.0,) + lens):
            point = vm.add(point, vm.mul(direction, l * hand))
            out[side + finger + segment] = point
    thumb_base = vm.add(vm.add(vm.add(wrist, vm.mul(d, 0.12 * hand)), vm.mul(w, -0.22 * hand)), vm.mul(n, 0.06 * hand))
    thumb_dir = vm.normalize(vm.add(vm.add(d, vm.mul(w, -0.75)), vm.mul(n, 0.25)))
    point = thumb_base
    for segment, l in zip(SEGMENTS + ("Tip",), (0.0, 0.20, 0.15, 0.13)):
        point = vm.add(point, vm.mul(thumb_dir, l * hand))
        out[side + "Thumb" + segment] = point
    return out


def template_landmarks(p: Proportions):
    """A-pose landmark template in metres (Z up, facing -Y)."""
    h = p.height
    lm = {}
    hunch = p.hunch * h
    for name, z, y in (("Hips", 0.53, 0.0), ("Spine", 0.60, 0.0), ("Chest", 0.67, -0.3), ("UpperChest", 0.74, -0.6),
                       ("Neck", 0.825, -1.0), ("Head", 0.87, -1.0)):
        lm[name] = (0.0, y * hunch, z * h)
    head_height = 0.13 * h * p.head_scale
    lm["HeadTop"] = (0.0, -hunch, lm["Head"][2] + head_height)
    angle = math.radians(p.arm_angle)
    for side, sgn in (("Left", 1.0), ("Right", -1.0)):
        shoulder = (sgn * p.shoulder_half * h, -0.6 * hunch, 0.81 * h)
        lm[side + "Shoulder"] = (sgn * 0.02 * h, -0.6 * hunch, 0.80 * h)
        lm[side + "UpperArm"] = shoulder
        direction = (sgn * math.cos(angle), 0.0, -math.sin(angle))
        arm = p.arm_length * h
        lm[side + "LowerArm"] = vm.add(shoulder, vm.mul(direction, arm * 0.42))
        wrist = vm.add(shoulder, vm.mul(direction, arm * (1 - 0.245 * p.hand_scale)))
        tip = vm.add(shoulder, vm.mul(direction, arm))
        lm[side + "Hand"] = wrist
        lm.update(finger_landmarks(side, wrist, tip))
        hip = (sgn * p.hip_half * h, 0.0, 0.50 * h)
        ankle_x = sgn * (p.hip_half + p.leg_spread) * h
        lm[side + "UpperLeg"] = hip
        lm[side + "LowerLeg"] = (vm.lerp(hip, (ankle_x, 0, 0), 0.45)[0], -0.01 * h, 0.285 * h)
        lm[side + "Foot"] = (ankle_x, 0.01 * h, 0.045 * h)
        lm[side + "Toes"] = (ankle_x, -0.085 * h, 0.012 * h)
        lm[side + "ToeTip"] = (ankle_x, -0.125 * h, 0.010 * h)
    return lm


def z_hint(name, landmarks):
    if name in TORSO:
        return (0.0, -1.0, 0.0)
    side = "Left" if name.startswith("Left") else "Right"
    part = name[len(side):]
    if part in ("Foot", "Toes"):
        return (0.0, 0.0, 1.0)
    if any(part.startswith(f) for f in FINGERS):
        _, n, _ = hand_frame(side, landmarks[side + "Hand"], landmarks[side + "MiddleProximal"])
        return n
    return (0.0, -1.0, 0.0)


# ---------------------------------------------------------------- skeleton

@dataclass
class Bone:
    name: str
    parent: str | None
    head: tuple
    tail: tuple
    matrix: list
    deform: bool = True

    @property
    def length(self):
        return vm.distance(self.head, self.tail)


@dataclass
class Skeleton:
    bones: dict = field(default_factory=dict)  # name -> Bone, parents before children
    landmarks: dict = field(default_factory=dict)

    def order(self):
        return list(self.bones)

    def children(self, name):
        return [b.name for b in self.bones.values() if b.parent == name]

    def descendants(self, name):
        result, stack = [], [name]
        while stack:
            current = stack.pop()
            for child in self.children(current):
                result.append(child)
                stack.append(child)
        return result

    def to_json(self):
        return {"format": "character-forge/skeleton@1",
                "bones": [{"name": b.name, "parent": b.parent, "head": list(b.head), "tail": list(b.tail),
                           "matrix": [list(r) for r in b.matrix], "deform": b.deform} for b in self.bones.values()],
                "landmarks": {k: list(v) for k, v in sorted(self.landmarks.items())}}

    @staticmethod
    def from_json(value):
        if value.get("format") != "character-forge/skeleton@1":
            raise ValueError("Not a character-forge skeleton")
        s = Skeleton()
        for b in value["bones"]:
            s.bones[b["name"]] = Bone(b["name"], b["parent"], tuple(b["head"]), tuple(b["tail"]),
                                      [list(map(float, r)) for r in b["matrix"]], bool(b.get("deform", True)))
        s.landmarks = {k: tuple(v) for k, v in value.get("landmarks", {}).items()}
        return s


def build_skeleton(landmarks, include_helpers=True) -> Skeleton:
    missing = [n for n in required_landmarks() if n not in landmarks]
    if missing:
        raise ValueError("Missing landmarks: " + ", ".join(missing[:8]))
    names = list(TORSO)
    for side in SIDES:
        names += [side + p for p in ARM]
        if include_helpers:
            names.append(side + "ForearmTwist")
        names += [side + f + s for f in FINGERS for s in SEGMENTS]
        names += [side + p for p in LEG]
    skeleton = Skeleton(landmarks=dict(landmarks))
    for name in names:
        if name.endswith("ForearmTwist"):
            side = name[:-len("ForearmTwist")]
            head = vm.lerp(landmarks[side + "LowerArm"], landmarks[side + "Hand"], 0.5)
            tail = landmarks[side + "Hand"]
        else:
            head, tail = landmarks[name], landmarks[tail_landmark(name)]
        if vm.distance(head, tail) < 1e-5:
            raise ValueError("Zero-length bone " + name)
        skeleton.bones[name] = Bone(name, parent_of(name), tuple(head), tuple(tail), vm.bone_matrix(head, tail, z_hint(name, landmarks)))
    return skeleton


# ---------------------------------------------------------------- landmark estimation from a mesh

def estimate_landmarks(vertices, proportions_hint: Proportions | None = None):
    """Heuristic A-pose landmarks for a normalized mesh (feet at z=0, centred on x). PROPOSAL quality:
    good enough to seed a rig; review/override landmarks.json for production characters."""
    zs = [v[2] for v in vertices]
    h = max(zs) - min(zs)
    p = proportions_hint or Proportions(height=h)
    p.height = h

    def slab(z0, z1, x0=-1e9, x1=1e9):
        return [v for v in vertices if z0 <= v[2] <= z1 and x0 <= v[0] <= x1]

    torso = slab(0.70 * h, 0.74 * h, -0.12 * h, 0.12 * h)
    if torso:
        half = percentile([abs(v[0]) for v in torso], 95)
        p.shoulder_half = max(0.09, min(0.18, half / h * 1.05))
    lm = template_landmarks(p)
    # Measure each arm from its most lateral point in the hand band (A-pose fingertips).
    for side, sgn in (("Left", 1.0), ("Right", -1.0)):
        band = [v for v in slab(0.25 * h, 0.80 * h) if sgn * v[0] > 0.12 * h]
        if band:
            tip = max(band, key=lambda v: sgn * v[0])
            shoulder = lm[side + "UpperArm"]
            direction = vm.normalize(vm.sub(tip, shoulder))
            arm = vm.distance(tip, shoulder)
            lm[side + "LowerArm"] = vm.add(shoulder, vm.mul(direction, arm * 0.42))
            wrist = vm.add(shoulder, vm.mul(direction, arm * 0.755))
            lm[side + "Hand"] = wrist
            lm.update(finger_landmarks(side, wrist, tip))
        legs = [v for v in slab(0.38 * h, 0.46 * h) if sgn * v[0] > 0.005 * h]
        if legs:
            x = sum(v[0] for v in legs) / len(legs)
            y = sum(v[1] for v in legs) / len(legs)
            for part in ("UpperLeg", "LowerLeg"):
                old = lm[side + part]
                lm[side + part] = (x, y if part == "UpperLeg" else old[1], old[2])
        feet = [v for v in slab(0.0, 0.08 * h) if sgn * v[0] > 0.0]
        if feet:
            x = sum(v[0] for v in feet) / len(feet)
            front = min(v[1] for v in feet)
            back = max(v[1] for v in feet)
            lm[side + "Foot"] = (x, back - 0.25 * (back - front), 0.045 * h)
            lm[side + "Toes"] = (x, front + 0.3 * (back - front), 0.012 * h)
            lm[side + "ToeTip"] = (x, front, 0.010 * h)
    for name in TORSO + ["HeadTop"]:
        z = lm[name][2]
        centre = [v for v in slab(z - 0.01 * h, z + 0.01 * h, -0.08 * h, 0.08 * h)]
        if centre:
            ys = [v[1] for v in centre]
            lm[name] = (0.0, (min(ys) + max(ys)) / 2, z)
    lm["HeadTop"] = (0.0, lm["Head"][1], max(zs) - 0.002 * h)
    return lm
