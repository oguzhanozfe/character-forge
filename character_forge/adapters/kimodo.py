"""Kimodo text-to-motion adapter (generate only the motions the shared library lacks) and its fake twin."""
from __future__ import annotations

from pathlib import Path

from ..lock import held
from ..meshkit.motion import procedural_clip
from ..util import ForgeError, read_json, write_json
from .base import KIMODO_SCRIPTS, REPO, run_command


def fake(requests, out_dir: Path, hip_height: float):
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for r in requests:
        clip = procedural_clip(r["kind"], r["id"], seed=int(r.get("seed", 0)), region=r.get("region"), hip_height=hip_height)
        clip["provenance"].update({"requested_prompt": r.get("prompt"), "generator": "fake (procedural stand-in for Kimodo)"})
        files.append(write_json(out_dir / (r["id"] + ".fmotion.json"), clip))
    return files


def real(machine, requests, out_dir: Path, log_path: Path, lock_dir: Path, owner: str, plan=None, mode="real"):
    python = machine.get("kimodo_python") or ""
    root = machine.get("kimodo_root") or ""
    if mode != "dry-run" and (not python or not root):
        raise ForgeError("Kimodo is not configured (kimodo_python/kimodo_root); run `forge setup` or use fake mode")
    out_dir.mkdir(parents=True, exist_ok=True)
    queue = write_json(out_dir / "queue.json", {"model": machine.get("kimodo_model", "Kimodo-SOMA-RP-v1.1"), "candidates": requests})
    command = [python or "kimodo_python", str(KIMODO_SCRIPTS / "generate_motions.py"), "--queue", str(queue),
               "--output", str(out_dir / "raw"), "--fmotion-dir", str(out_dir), "--kimodo-root", root or "kimodo_root",
               "--forge-repo", str(REPO)]
    env = {"TEXT_ENCODER_DEVICE": machine.get("kimodo_text_encoder_device", "cpu"), "HF_HUB_OFFLINE": "1",
           "TRANSFORMERS_OFFLINE": "1"}
    if mode == "dry-run":
        run_command(command, log_path, env=env, plan=plan, mode=mode)
    with held(lock_dir, "gpu", owner, timeout=6 * 3600):
        run_command(command, log_path, env=env, timeout=6 * 3600)
    files = []
    for r in requests:
        path = out_dir / (r["id"] + ".fmotion.json")
        if not path.is_file():
            raise ForgeError("Kimodo finished without %s (log %s)" % (path.name, log_path))
        if read_json(path).get("format") != "character-forge/motion@1":
            raise ForgeError("Kimodo output %s is not an fmotion clip" % path.name)
        files.append(path)
    return files
