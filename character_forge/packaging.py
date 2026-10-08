"""Final-form packaging rules: only the model FBX, runtime textures, motion FBX clips, the manifest and a concise
receipt may leave the workspace. Intermediates (.blend, .glb, .ply, .npz, .obj, raw BVH, renders, weights, logs)
are refused."""
from __future__ import annotations

import re
from pathlib import Path

from .util import ForgeError, files_under

ALLOWED_TOP = {"character.manifest.json", "receipt.json", "README.txt"}
TEXTURE_SUFFIXES = {".png", ".tga", ".jpg", ".jpeg", ".exr"}
INTERMEDIATE_SUFFIXES = {".blend", ".blend1", ".blend2", ".glb", ".gltf", ".ply", ".npz", ".npy", ".obj", ".mtl", ".bvh",
                         ".ckpt", ".safetensors", ".gguf", ".pt", ".pth", ".onnx", ".bin", ".log", ".tmp", ".zip", ".7z",
                         ".psd", ".kra", ".spp", ".ztl", ".usd", ".usda", ".usdc", ".abc", ".mp4", ".webm", ".gif"}
REVIEW_WORDS = ("review", "contact", "sheet", "preview", "render", "turntable", "debug", "screenshot", "candidate", "raw")


def problems(directory: Path, character_id: str, max_mb=None):
    directory = Path(directory)
    issues = []
    total = 0
    for path in files_under(directory):
        rel = path.relative_to(directory).as_posix()
        total += path.stat().st_size
        suffix = path.suffix.lower()
        lowered = rel.lower()
        if suffix in INTERMEDIATE_SUFFIXES:
            issues.append("intermediate file type %s: %s" % (suffix, rel))
            continue
        tokens = set(re.split(r"[^a-z0-9]+", lowered.replace(character_id.lower(), " ")))
        if tokens & set(REVIEW_WORDS):
            issues.append("review/intermediate artefact name: %s" % rel)
            continue
        parts = rel.split("/")
        if len(parts) == 1:
            if rel not in ALLOWED_TOP and rel != character_id + ".fbx":
                issues.append("unexpected top-level file: %s" % rel)
        elif parts[0] == "Textures" and len(parts) == 2:
            if suffix not in TEXTURE_SUFFIXES:
                issues.append("non-texture in Textures/: %s" % rel)
        elif parts[0] == "Motions" and len(parts) == 2:
            if suffix != ".fbx" or not parts[1].startswith(character_id + "@"):
                issues.append("Motions/ must hold <id>@<clip>.fbx only: %s" % rel)
        else:
            issues.append("unexpected location: %s" % rel)
    if not (directory / (character_id + ".fbx")).is_file():
        issues.append("missing model %s.fbx" % character_id)
    if not (directory / "character.manifest.json").is_file():
        issues.append("missing character.manifest.json")
    if max_mb and total > max_mb * 1024 * 1024:
        issues.append("package is %.1f MB, over the %s MB budget" % (total / 1048576, max_mb))
    return issues


def verify(directory: Path, character_id: str, max_mb=None):
    issues = problems(directory, character_id, max_mb)
    if issues:
        raise ForgeError("Package refused (%d problem%s):\n  - %s" % (len(issues), "s" if len(issues) != 1 else "", "\n  - ".join(issues)))
    return True
