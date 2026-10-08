"""Neutral motion format, procedural clips, retargeting onto a character skeleton and motion screening.

Motion format `character-forge/motion@1` ("fmotion"): per contract bone, a global rotation *delta relative to the
standard T-pose* per frame (Kimodo/SOMA `standard_tpose` global rotations converted to Z-up), plus the Hips
position track. Any character whose skeleton follows the contract can play it: we rebuild the character's own
T-pose orientation for each bone and compose. Python is the single source of truth for the retarget; Blender only
writes the baked local rotations into FBX actions.
"""
from __future__ import annotations

import math

from . import vecmath as vm
from .analysis import edge_stretch
from .skeleton import FINGERS, SIDES, Skeleton, parent_of
from .skinning import deform, skin_matrices

FORMAT = "character-forge/motion@1"
BAKED_FORMAT = "character-forge/baked-motion@1"
GROUNDED_KINDS = {"Idle", "Walk", "Run", "Attack", "Hit", "Alert", "Stagger"}
LOOP_KINDS = {"Idle", "Walk", "Run", "Crawl", "CrawlIdle", "Stun"}

# SOMA (Kimodo) joint names -> contract names (from the verified Z01 retargeter mapping).
SOMA_MAPPING = {"Hips": "Hips", "Spine": "Spine1", "Chest": "Spine2", "UpperChest": "Chest", "Neck": "Neck1", "Head": "Head"}
for _side in SIDES:
    for _t, _s in (("Shoulder", "Shoulder"), ("UpperArm", "Arm"), ("LowerArm", "ForeArm"), ("Hand", "Hand"),
                   ("UpperLeg", "Leg"), ("LowerLeg", "Shin"), ("Foot", "Foot"), ("Toes", "ToeBase")):
        SOMA_MAPPING[_side + _t] = _side + _s
    for _f, _soma in (("Thumb", "Thumb"), ("Index", "Index"), ("Middle", "Middle"), ("Ring", "Ring"), ("Little", "Pinky")):
        for _seg, _j in zip(("Proximal", "Intermediate", "Distal"), (1, 2, 3) if _f == "Thumb" else (2, 3, 4)):
            SOMA_MAPPING[_side + _f + _seg] = _side + "Hand" + _soma + str(_j)
# SOMA: x right, y up, z forward  ->  forge/Blender: x right, y backward, z up.
SOMA_TO_FORGE = [[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]]


def contract_order(names):
    """Parents before children for any subset of contract bones."""
    depth = {}

    def d(n):
        if n not in depth:
            p = parent_of(n)
            depth[n] = 0 if p is None else d(p) + 1
        return depth[n]

    return sorted(names, key=lambda n: (d(n), n))


# ---------------------------------------------------------------- procedural clips (own-authored, licence-clean)

def _compose(rel_tracks, frames, bones):
    """rel_tracks: {bone: f(t)->quat about world axes in the parent's T frame}. Returns global deltas."""
    out = {b: [] for b in bones}
    for f in range(frames):
        g = {}
        for b in contract_order(bones):
            parent = parent_of(b)
            rel = rel_tracks.get(b, lambda _f: vm.quat_identity())(f)
            g[b] = vm.quat_mul(g[parent], rel) if parent in g else rel
            out[b].append([round(c, 6) for c in vm.quat_normalize(g[b])])
    return out


def procedural_clip(kind, clip_id, seed=0, region=None, fps=30, seconds=None, hip_height=0.95):
    """Crude but valid own-authored motion for fake mode and for smoke-testing a real character."""
    from .skeleton import HUMAN_BONES
    rng = (seed * 7919 + 17) % 1000 / 1000.0
    seconds = seconds or {"Idle": 2.0, "Walk": 1.2, "Run": 0.8, "Attack": 1.4, "Hit": 0.9, "Death": 2.0}.get(kind, 1.5)
    frames = int(round(seconds * fps)) + 1
    T = frames - 1
    axis = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}

    def q(ax, deg):
        return vm.quat_axis_angle(axis[ax], deg)

    def cyc(f, phase=0.0):
        return math.sin(2 * math.pi * (f / T + phase))

    arm_down = {"Left": lambda f: q("y", 72), "Right": lambda f: q("y", -72)}
    tracks = {}
    root = []
    amp = 1.0 + 0.3 * rng
    if kind in ("Idle", "Walk", "Run"):
        stride = {"Idle": 0.0, "Walk": 28.0, "Run": 42.0}[kind] * amp
        for side, sgn, ph in (("Left", 1, 0.0), ("Right", -1, 0.5)):
            tracks[side + "UpperArm"] = (lambda f, p=ph, side=side: vm.quat_mul(q("x", -stride * 0.6 * cyc(f, p) - 12), arm_down[side](f)))
            tracks[side + "LowerArm"] = (lambda f, s=sgn: q("z", -s * (25 + 5 * rng)))
            tracks[side + "UpperLeg"] = (lambda f, p=ph: q("x", -stride * cyc(f, p + 0.5)))
            tracks[side + "LowerLeg"] = (lambda f, p=ph: q("x", stride * 1.2 * max(0.0, cyc(f, p + 0.75))))
        tracks["Spine"] = lambda f: q("x", 8 + 6 * rng + (2 * cyc(f) if kind == "Idle" else 0))
        tracks["Neck"] = lambda f: q("x", 6)
        for f in range(frames):
            bob = 0.004 * cyc(f) if kind == "Idle" else 0.015 * abs(cyc(f, 0.25))
            root.append([0.0, 0.0, hip_height + bob])
        loop = True
    elif kind == "Attack":
        side = "Right" if rng < 0.6 else "Left"
        sgn = -1 if side == "Right" else 1
        impact = 0.55

        def arm(f, side=side):
            t = f / T
            raise_deg = 110 * math.sin(math.pi * 0.5 * t / impact) if t < impact else 110 * (1 - (t - impact) / (1 - impact))
            return vm.quat_mul(q("x", -raise_deg), arm_down[side](f))

        tracks[side + "UpperArm"] = arm
        other = "Left" if side == "Right" else "Right"
        tracks[other + "UpperArm"] = arm_down[other]
        tracks["Spine"] = lambda f: vm.quat_mul(q("z", sgn * 20 * math.sin(math.pi * f / T)), q("x", 10))
        for f in range(frames):
            root.append([0.0, -0.08 * math.sin(math.pi * f / T), hip_height])
        loop = False
    elif kind == "Hit":
        target = region or "Chest"
        sign = 1 if target == "Back" else -1          # recoil away from the hit
        torso_bone = {"Head": "Neck", "Neck": "Neck", "Chest": "Chest", "Back": "Chest", "Abdomen": "Spine", "Pelvis": "Spine"}.get(target)
        for side in SIDES:
            tracks[side + "UpperArm"] = arm_down[side]
        if torso_bone:
            tracks[torso_bone] = lambda f: q("x", sign * 25 * math.sin(math.pi * f / T) * amp)
        else:
            side = "Left" if target.startswith("Left") else "Right"
            part = target[len(side):]
            s = 1 if side == "Left" else -1
            if part in ("Shoulder", "UpperArm"):
                tracks[side + "UpperArm"] = lambda f, side=side: vm.quat_mul(q("x", 25 * math.sin(math.pi * f / T)), arm_down[side](f))
            elif part in ("Forearm", "Hand"):
                tracks[side + ("LowerArm" if part == "Forearm" else "Hand")] = lambda f, s=s: q("z", -s * 35 * math.sin(math.pi * f / T))
            else:
                bone = side + {"Thigh": "UpperLeg", "LowerLeg": "LowerLeg", "Foot": "Foot"}[part]
                tracks[bone] = lambda f: q("x", 18 * math.sin(math.pi * f / T))
            tracks["Spine"] = lambda f: q("x", -8 * math.sin(math.pi * f / T))
        for f in range(frames):
            root.append([0.0, 0.04 * math.sin(math.pi * f / T), hip_height])
        loop = False
    elif kind == "Death":
        for side in SIDES:
            tracks[side + "UpperArm"] = arm_down[side]
            tracks[side + "UpperLeg"] = (lambda f: q("x", -50 * min(1.0, 1.6 * f / T)))
            tracks[side + "LowerLeg"] = (lambda f: q("x", 95 * min(1.0, 1.6 * f / T)))
        tracks["Spine"] = lambda f: q("x", 35 * min(1.0, 1.4 * f / T))
        for f in range(frames):
            fall = min(1.0, 1.6 * f / T)
            root.append([0.0, 0.0, hip_height * (1 - 0.30 * fall)])
        loop = False
    else:
        for side in SIDES:
            tracks[side + "UpperArm"] = arm_down[side]
        root = [[0.0, 0.0, hip_height] for _ in range(frames)]
        loop = kind in LOOP_KINDS
    bones = list(HUMAN_BONES)
    clip = {"format": FORMAT, "id": clip_id, "kind": kind, "region": region, "fps": fps, "frames": frames,
            "loop": loop, "in_place": True, "space": "tpose-global", "up": "z", "forward": "-y",
            "reference_hip_height": hip_height, "root": root, "rotations": _compose(tracks, frames, bones),
            "events": {"impact_seconds": round(0.55 * (frames - 1) / fps, 4)} if kind == "Attack" else {},
            "provenance": {"source": "character-forge procedural generator", "seed": seed,
                           "licence": "Own-authored procedural data (repository licence)", "quality": "smoke-test only"}}
    return clip


def fmotion_from_global_rotations(clip_id, kind, joint_names, global_rots, root_positions, fps, region=None,
                                  loop=None, mapping=SOMA_MAPPING, conversion=SOMA_TO_FORGE, remove_heading=True,
                                  provenance=None, reference_hip_height=None):
    """Convert generator output (per-frame global rotation matrices relative to a standard T-pose, y-up) to fmotion.

    global_rots: [frame][joint] 3x3 nested lists; root_positions: [frame] xyz (generator space, metres).
    Pure Python so it is testable without numpy/torch; Kimodo's script passes `.tolist()` arrays.
    """
    index = {n: i for i, n in enumerate(joint_names)}
    c = conversion
    ct = vm.mat3_transpose(c)
    heading = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    if remove_heading and "Hips" in mapping and mapping["Hips"] in index:
        hips = index[mapping["Hips"]]
        fx = sum(frame[hips][0][2] for frame in global_rots) / len(global_rots)
        fz = sum(frame[hips][2][2] for frame in global_rots) / len(global_rots)
        yaw = math.atan2(fx, fz)
        cy, sy = math.cos(-yaw), math.sin(-yaw)
        heading = [[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]]  # rotation about generator +Y
    conv = vm.mat3_mul(c, heading)
    rotations = {}
    for bone, source in mapping.items():
        if source not in index:
            continue
        j = index[source]
        rotations[bone] = [[round(x, 6) for x in vm.mat3_to_quat(vm.mat3_mul(vm.mat3_mul(conv, frame[j]), ct))] for frame in global_rots]
    origin = vm.mat3_apply(conv, root_positions[0])
    root = []
    for p in root_positions:
        v = vm.mat3_apply(conv, p)
        root.append([round(v[0] - origin[0], 6), round(v[1] - origin[1], 6), round(v[2], 6)])
    hip = reference_hip_height or (sum(r[2] for r in root) / len(root))
    return {"format": FORMAT, "id": clip_id, "kind": kind, "region": region, "fps": fps, "frames": len(global_rots),
            "loop": kind in LOOP_KINDS if loop is None else bool(loop), "in_place": False, "space": "tpose-global",
            "up": "z", "forward": "-y", "reference_hip_height": hip, "root": root, "rotations": rotations,
            "events": {}, "provenance": provenance or {}}


# ---------------------------------------------------------------- retarget

def tpose_alignment(skeleton: Skeleton):
    """Rotation A(bone) that takes the character's rest (often A-pose) orientation to its T-pose orientation.

    Arm chains are straightened to +/-X; fingers and the twist helper follow their hand/forearm; the torso,
    shoulders and legs are assumed upright already.
    """
    align = {}
    for name, bone in skeleton.bones.items():
        inherited = align.get(bone.parent, vm.quat_identity()) if bone.parent else vm.quat_identity()
        side = "Left" if name.startswith("Left") else ("Right" if name.startswith("Right") else None)
        part = name[len(side):] if side else name
        if side and part in ("UpperArm", "LowerArm", "Hand"):
            target = (1.0, 0.0, 0.0) if side == "Left" else (-1.0, 0.0, 0.0)
            current = vm.quat_rotate(inherited, vm.normalize(vm.sub(bone.tail, bone.head)))
            align[name] = vm.quat_mul(vm.rotation_between(current, target), inherited)
        elif side and (part == "ForearmTwist" or any(part.startswith(f) for f in FINGERS)):
            align[name] = inherited
        else:
            align[name] = vm.quat_identity()
    return align


def retarget(clip, skeleton: Skeleton, in_place=None):
    """Bake an fmotion clip into local basis rotations (and Hips location) for this skeleton."""
    if clip.get("format") != FORMAT:
        raise ValueError("Not a character-forge motion clip: " + str(clip.get("id")))
    align = tpose_alignment(skeleton)
    rest_q = {n: vm.mat3_to_quat(vm.mat_rot3(b.matrix)) for n, b in skeleton.bones.items()}
    tpose_q = {n: vm.quat_mul(align[n], rest_q[n]) for n in skeleton.bones}
    hips = skeleton.bones["Hips"]
    scale = hips.head[2] / float(clip.get("reference_hip_height") or hips.head[2])
    in_place = clip.get("in_place", False) if in_place is None else in_place
    frames = clip["frames"]
    root = clip["root"]
    travel = (root[-1][0] - root[0][0], root[-1][1] - root[0][1])
    bones = {n: [] for n in skeleton.bones}
    hips_location = []
    for f in range(frames):
        world = {}
        for name, bone in skeleton.bones.items():
            track = clip["rotations"].get(name)
            if track is not None:
                g = tuple(track[f])
            else:
                # Untracked bone (e.g. a helper): keep its rest relation to the parent.
                g = None
            if g is not None:
                world[name] = vm.quat_mul(g, tpose_q[name])
            elif bone.parent:
                rel = vm.quat_mul(vm.quat_conj(rest_q[bone.parent]), rest_q[name])
                world[name] = vm.quat_mul(world[bone.parent], rel)
            else:
                world[name] = rest_q[name]
            parent_rest = rest_q[bone.parent] if bone.parent else vm.quat_identity()
            parent_world = world[bone.parent] if bone.parent else vm.quat_identity()
            basis = vm.quat_mul(vm.quat_mul(vm.quat_mul(vm.quat_conj(rest_q[name]), parent_rest), vm.quat_conj(parent_world)), world[name])
            bones[name].append([round(c, 6) for c in vm.quat_normalize(basis)])
        x, y, z = root[f]
        if in_place:
            k = f / (frames - 1) if frames > 1 else 0.0
            x -= root[0][0] + travel[0] * k
            y -= root[0][1] + travel[1] * k
        desired = (x * scale, hips.head[1] + y * scale, z * scale)
        delta = vm.sub(desired, hips.head)
        local = vm.mat3_apply(vm.mat3_transpose(vm.mat_rot3(hips.matrix)), delta)
        hips_location.append([round(c, 6) for c in local])
    seconds = (frames - 1) / clip["fps"] if frames > 1 else 0.0
    speed = math.hypot(*travel) * scale / seconds if seconds > 0 else 0.0
    return {"format": BAKED_FORMAT, "id": clip["id"], "kind": clip.get("kind"), "region": clip.get("region"),
            "fps": clip["fps"], "frames": frames, "loop": bool(clip.get("loop")), "in_place": bool(in_place),
            "suggested_speed_m_s": round(speed, 4), "events": clip.get("events", {}), "bones": bones,
            "hips_location": hips_location, "provenance": clip.get("provenance", {})}


def bone_radii(skeleton: Skeleton, vertices, weights, q=90):
    """Per-bone flesh radius: percentile distance of vertices dominated by the bone to its segment."""
    from .util_stats import percentile
    samples = {}
    for v, row in zip(vertices, weights):
        if row:
            name = max(row, key=lambda item: item[1])[0]
            bone = skeleton.bones.get(name)
            if bone is not None:
                samples.setdefault(name, []).append(vm.point_segment_distance(v, bone.head, bone.tail)[0])
    return {name: percentile(values, q) for name, values in samples.items()}


def _lowest_flesh(world, skeleton, radii):
    lowest = float("inf")
    for name, m in world.items():
        bone = skeleton.bones[name]
        r = radii.get(name, 0.0)
        head = vm.mat_translation(m)
        tail = vm.mat_apply(m, (0.0, bone.length, 0.0))
        lowest = min(lowest, min(head[2], tail[2]) - r)
    return lowest


def ground_clamp(baked, skeleton: Skeleton, radii, kinds=GROUNDED_KINDS | {"Death", "Knockdown", "GetUp"}):
    """Raise the Hips on frames where the bone-capsule approximation of the body sinks below its rest floor level.

    Cheap stand-in for the Z01 per-vertex CPU ground clamp; the motion screen still measures real vertices."""
    from .skinning import posed_world
    if baked.get("kind") not in kinds:
        return baked
    rest_floor = _lowest_flesh({n: b.matrix for n, b in skeleton.bones.items()}, skeleton, radii)
    hips = skeleton.bones["Hips"]
    to_local = vm.mat3_transpose(vm.mat_rot3(hips.matrix))
    lifted = 0.0
    for f in range(baked["frames"]):
        low = _lowest_flesh(posed_world(skeleton, baked_basis(baked, f)), skeleton, radii)
        lift = rest_floor - low
        if lift > 0:
            delta = vm.mat3_apply(to_local, (0.0, 0.0, lift))
            baked["hips_location"][f] = [round(a + b, 6) for a, b in zip(baked["hips_location"][f], delta)]
            lifted = max(lifted, lift)
    baked["ground_clamp_max_m"] = round(lifted, 4)
    return baked


def baked_basis(baked, frame):
    basis = {}
    for name, track in baked["bones"].items():
        t = tuple(baked["hips_location"][frame]) if name == "Hips" else (0.0, 0.0, 0.0)
        basis[name] = (tuple(track[frame]), t)
    return basis


# ---------------------------------------------------------------- screening

def screen(baked, skeleton: Skeleton, vertices, weights, edges, height, samples=10, thresholds=None):
    th = {"floor_penetration_m": 0.03, "floating_m": 0.06, "loop_seam_m": 0.02, "stretch_red_flag": 3.0}
    th.update(thresholds or {})
    frames = baked["frames"]
    picks = sorted({0, frames - 1} | {round(i * (frames - 1) / max(1, samples - 1)) for i in range(samples)})
    impact = baked.get("events", {}).get("impact_seconds")
    impact_frame = None
    if impact is not None:
        impact_frame = min(frames - 1, max(0, round(impact * baked["fps"])))
        picks = sorted(set(picks) | {impact_frame})
    finite = True
    lowest, highest_low = float("inf"), -float("inf")
    worst_stretch, over = 1.0, 0
    posed_cache = {}
    reach = None
    for f in picks:
        posed = deform(vertices, weights, skin_matrices(skeleton, baked_basis(baked, f)))
        posed_cache[f] = posed
        if not all(math.isfinite(c) for p in posed for c in p):
            finite = False
            continue
        low = min(p[2] for p in posed)
        lowest = min(lowest, low)
        highest_low = max(highest_low, low)
        st = edge_stretch(vertices, posed, edges, red_flag=th["stretch_red_flag"], worst=0)
        worst_stretch = max(worst_stretch, st["max_ratio"])
        over = max(over, st["over_red_flag"])
        if f == impact_frame:
            hips_y = sum(p[1] for p in posed) / len(posed)
            reach = round((hips_y - min(p[1] for p in posed)) / height, 4)
    seam = None
    if baked.get("loop") and finite:
        a, b = posed_cache[0], posed_cache[frames - 1]
        seam = max(vm.distance(p, q) for p, q in zip(a, b))
    grounded = baked.get("kind") in GROUNDED_KINDS
    problems = []
    if not finite:
        problems.append("nonfinite skinned vertices")
    penetration = max(0.0, -lowest) if finite else None
    if finite and penetration > th["floor_penetration_m"]:
        problems.append("floor penetration %.3f m" % penetration)
    if finite and grounded and lowest > th["floating_m"]:
        problems.append("body never reaches the floor (lowest %.3f m)" % lowest)
    if seam is not None and seam > th["loop_seam_m"]:
        problems.append("loop seam %.3f m" % seam)
    if over:
        problems.append("%d edges over %.1fx stretch" % (over, th["stretch_red_flag"]))
    if impact is not None and not (0.05 < impact < (frames - 1) / baked["fps"]):
        problems.append("attack impact outside clip")
    return {"clip": baked["id"], "kind": baked.get("kind"), "region": baked.get("region"), "frames": frames,
            "sampled_frames": len(picks), "finite": finite, "lowest_point_m": round(lowest, 4) if finite else None,
            "floor_penetration_m": round(penetration, 4) if penetration is not None else None,
            "loop_seam_m": round(seam, 4) if seam is not None else None, "max_edge_stretch": round(worst_stretch, 4),
            "edges_over_red_flag": over, "attack_reach_per_height": reach,
            "suggested_speed_m_s": baked.get("suggested_speed_m_s"),
            "status": "PASS" if not problems else ("FAIL" if not finite else "WARN"), "problems": problems}
