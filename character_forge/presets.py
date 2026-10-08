"""Character presets (zombie, humanoid, ...): bone/hitbox/gore contracts, budgets, thresholds, motion profiles."""
from __future__ import annotations

import json
from pathlib import Path

from .meshkit.skeleton import FINGER_BONES, HUMAN_BONES, UNITY_REQUIRED
from .util import ForgeError

PRESET_DIR = Path(__file__).with_name("data") / "presets"


def available():
    return sorted(p.stem for p in PRESET_DIR.glob("*.json"))


def load(name: str, extra_dirs=()):
    for directory in [*map(Path, extra_dirs), PRESET_DIR]:
        path = directory / (name + ".json")
        if path.is_file():
            preset = json.loads(path.read_text(encoding="utf-8"))
            preset.setdefault("name", name)
            return preset
    raise ForgeError("Unknown preset %r (available: %s)" % (name, ", ".join(available())))


def required_bones(preset):
    if preset.get("require_all_human_bones"):
        return list(HUMAN_BONES)
    bones = list(UNITY_REQUIRED)
    if preset.get("require_fingers"):
        bones += FINGER_BONES
    return bones


def motion_slots(preset, profile=None):
    """Expand a motion profile into concrete slots: [(kind, region or None)]."""
    profile = profile or preset.get("default_motion_profile", "pilot")
    spec = preset.get("motion_profiles", {}).get(profile)
    if spec is None:
        raise ForgeError("Preset %s has no motion profile %r" % (preset["name"], profile))
    slots = []
    for kind, count in spec.items():
        if kind == "HitPerRegion":
            for region in preset.get("hit_regions", {}):
                slots += [("Hit", region)] * int(count)
        elif kind == "Hit" and isinstance(count, dict):
            for region, n in count.items():
                slots += [("Hit", region)] * int(n)
        else:
            slots += [(kind, None)] * int(count)
    return slots
