"""character.manifest.json: the contract the Unity package reads (model, textures, Humanoid map, hitboxes, gore, motions)."""
from __future__ import annotations

import shutil
from pathlib import Path

from .meshkit.skeleton import HUMAN_BONES
from .util import read_json, write_json

FORMAT = "character-forge/manifest@1"
FAKE_FBX = b"; FBX 7.4.0 project file\n; character-forge FAKE-MODE PLACEHOLDER - not a real model. Run in real mode.\n"


def build(ws, character, preset, inputs, mode, motions=None):
    """Arrays of objects only (no dictionaries) so Unity's JsonUtility can read it without extra packages."""
    from .presets import required_bones
    skeleton = read_json(inputs["rig.skeleton"])
    names = {b["name"] for b in skeleton["bones"]}
    textures = [{"channel": k.split(".", 1)[1], "file": "Textures/%s" % Path(v).name}
                for k, v in sorted(inputs.items()) if k.startswith("lowmesh.texture.")]
    return {"format": FORMAT, "id": ws.id, "preset": preset["name"], "height_m": character["params"]["height_m"],
            "mode": mode, "model": ws.id + ".fbx",
            "materials": [{"name": ws.id + "_Body", "textures": textures}],
            "humanoid": [{"human": b, "bone": b} for b in HUMAN_BONES if b in names],
            "required_bones": required_bones(preset),
            "helpers": [b["name"] for b in skeleton["bones"] if b["name"] not in HUMAN_BONES],
            "hitboxes": [{k: h.get(k) for k in ("region", "bone", "side", "radius_m", "length_m", "vertices")}
                         for h in read_json(inputs["rig.hitboxes"])["hitboxes"]],
            "gore": [{"part": g["part"], "bone": g["bone"]} for g in read_json(inputs["rig.gore"])["gore"]],
            "motions": motions or []}


def stage_model(target: Path, ws, inputs, mode):
    """Copy the final model FBX and runtime textures into a package-layout folder."""
    target.mkdir(parents=True, exist_ok=True)
    model = target / (ws.id + ".fbx")
    if "rig.fbx" in inputs and mode != "fake":
        shutil.copyfile(inputs["rig.fbx"], model)
    else:
        model.write_bytes(FAKE_FBX)
    (target / "Textures").mkdir(exist_ok=True)
    for key, path in inputs.items():
        if key.startswith("lowmesh.texture."):
            shutil.copyfile(path, target / "Textures" / Path(path).name)
    return model


def write(target: Path, manifest):
    return write_json(Path(target) / "character.manifest.json", manifest)
