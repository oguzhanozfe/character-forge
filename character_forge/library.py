"""Shared motion libraries: an index (library.json) of fmotion clips with kind/region/provenance/licence.

Author motion once, fit and validate it on each character; generate only what the library lacks.
"""
from __future__ import annotations

from pathlib import Path

from .meshkit.motion import FORMAT as MOTION_FORMAT
from .meshkit.motion import procedural_clip
from .util import ForgeError, read_json, write_json

INDEX = "library.json"
FORMAT = "character-forge/motion-library@1"


def load(directory: Path):
    path = Path(directory) / INDEX
    if not path.is_file():
        return None
    data = read_json(path)
    if data.get("format") != FORMAT:
        raise ForgeError("%s is not a character-forge motion library" % path)
    clips = []
    for clip in data.get("clips", []):
        file = Path(directory) / clip["file"]
        clips.append(dict(clip, path=file, library=data.get("name", Path(directory).name)))
    return {"name": data.get("name", Path(directory).name), "dir": Path(directory), "clips": clips, "index": path}


def add_clip(directory: Path, clip_path: Path, licence: str, tags=(), copy=True):
    directory = Path(directory)
    clip = read_json(clip_path)
    if clip.get("format") != MOTION_FORMAT:
        raise ForgeError("Not an fmotion clip: %s" % clip_path)
    index_path = directory / INDEX
    data = read_json(index_path) if index_path.is_file() else {"format": FORMAT, "name": directory.name, "clips": []}
    if any(c["id"] == clip["id"] for c in data["clips"]):
        raise ForgeError("Library %s already has clip %s" % (directory, clip["id"]))
    target = directory / "clips" / (clip["id"] + ".fmotion.json")
    if copy:
        write_json(target, clip)
    data["clips"].append({"id": clip["id"], "kind": clip["kind"], "region": clip.get("region"),
                          "file": target.relative_to(directory).as_posix(), "tags": list(tags), "licence": licence,
                          "source": clip.get("provenance", {}).get("source", "unknown")})
    write_json(index_path, data)
    return target


def synth(directory: Path, regions=(), name="procedural-starter", hip_height=0.95):
    """Write a small own-authored procedural library (smoke-test quality) so the pipeline runs end to end."""
    directory = Path(directory)
    if (directory / INDEX).exists():
        raise ForgeError("%s already contains a library; choose another directory." % directory)
    clips = [("Idle", None), ("Walk", None), ("Run", None), ("Attack", None), ("Death", None)] + [("Hit", r) for r in regions]
    data = {"format": FORMAT, "name": name, "clips": []}
    for n, (kind, region) in enumerate(clips):
        clip_id = "Proc_%s%s_01" % (kind, "_" + region if region else "")
        clip = procedural_clip(kind, clip_id, seed=n + 1, region=region, hip_height=hip_height)
        path = write_json(directory / "clips" / (clip_id + ".fmotion.json"), clip)
        data["clips"].append({"id": clip_id, "kind": kind, "region": region, "file": path.relative_to(directory).as_posix(),
                              "tags": ["procedural", "smoke-test"], "licence": "own-authored procedural (repository licence)",
                              "source": "character-forge procedural generator"})
    write_json(directory / INDEX, data)
    return directory / INDEX


def select(libraries, slots, include=(), exclude=()):
    """Fill (kind, region) slots from libraries in order; explicit includes first. Returns (chosen, missing)."""
    pool = [c for lib in libraries for c in lib["clips"] if c["id"] not in set(exclude)]
    by_id = {c["id"]: c for c in pool}
    used, chosen, missing = set(), [], []
    forced = [by_id[i] for i in include if i in by_id]
    unknown = [i for i in include if i not in by_id]
    if unknown:
        raise ForgeError("motions.include lists clips not found in any library: " + ", ".join(unknown))
    for kind, region in slots:
        pick = None
        for candidate in forced + pool:
            if candidate["id"] in used or candidate["kind"] != kind:
                continue
            if kind == "Hit" and region and candidate.get("region") != region:
                continue
            pick = candidate
            break
        if pick:
            used.add(pick["id"])
            chosen.append({"slot": [kind, region], "clip": pick})
        else:
            missing.append([kind, region])
    # Explicit includes that matched no slot are still part of the character's set.
    for c in forced:
        if c["id"] not in used:
            used.add(c["id"])
            chosen.append({"slot": [c["kind"], c.get("region")], "clip": c})
    return chosen, missing
