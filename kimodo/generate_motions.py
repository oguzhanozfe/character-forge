"""Generate missing motions with a local Kimodo install and convert them to character-forge fmotion clips.

Runs inside Kimodo's own Python (it needs torch + kimodo). Started by character-forge's Kimodo adapter while it holds
the machine-wide `gpu` lock; never run it beside another GPU job. Offline: the text encoder and weights must already
be installed locally (TEXT_ENCODER_DEVICE=cpu keeps VRAM use small).

  <kimodo python> generate_motions.py --queue queue.json --output <dir>/raw --fmotion-dir <dir> \
      --kimodo-root <kimodo checkout> --forge-repo <character-forge checkout>

queue.json: {"model": "Kimodo-SOMA-RP-v1.1", "candidates": [{"id", "kind", "region", "prompt", "seconds", "seed", "loop"}]}
Raw NPZ/BVH stay in --output (intermediates, never packaged). Licence: check the selected checkpoint's terms
(SOMA-RP: NVIDIA Open Model licence; SMPLX-RP: internal R&D only) before shipping generated motion.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fmotion-dir", required=True, type=Path)
    parser.add_argument("--kimodo-root", required=True, type=Path)
    parser.add_argument("--forge-repo", required=True, type=Path)
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()
    queue = json.loads(args.queue.read_text(encoding="utf-8"))
    specs = queue["candidates"]
    if not specs or len({s["id"] for s in specs}) != len(specs):
        raise SystemExit("queue needs unique candidate ids")
    for s in specs:
        if not s["id"].replace("_", "").replace("-", "").isalnum() or not 1 <= float(s["seconds"]) <= 10:
            raise SystemExit("safe ids and 1..10 s durations required: %s" % s["id"])
    args.output.mkdir(parents=True, exist_ok=True)
    args.fmotion_dir.mkdir(parents=True, exist_ok=True)
    os.environ.update(TEXT_ENCODER_MODE="local", LOCAL_CACHE="true", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    sys.path.insert(0, str(args.kimodo_root))
    sys.path.insert(0, str(args.forge_repo))
    import numpy as np
    import torch
    from kimodo import load_model
    from kimodo.exports.bvh import save_motion_bvh
    from kimodo.exports.motion_io import save_kimodo_npz
    from kimodo.skeleton import SOMASkeleton30, global_rots_to_local_rots
    from kimodo.tools import seed_everything

    from character_forge.meshkit.motion import fmotion_from_global_rotations

    model_name = queue.get("model", "Kimodo-SOMA-RP-v1.1")
    print("LOADING_LOCAL_KIMODO", model_name, flush=True)
    model = load_model(model_name, device=args.device)
    skeleton = model.skeleton.somaskel77 if isinstance(model.skeleton, SOMASkeleton30) else model.skeleton
    skeleton = skeleton.to(args.device)
    names = list(skeleton.bone_order_names)
    foot_ids = [i for i, n in enumerate(names) if "Toe" in n or n.endswith("Foot")]
    for spec in specs:
        target = args.fmotion_dir / (spec["id"] + ".fmotion.json")
        if target.exists():
            print("EXISTS", spec["id"], flush=True)
            continue
        seed_everything(int(spec.get("seed", 0)))
        started = time.monotonic()
        print("GENERATING", spec["id"], flush=True)
        motion = model([spec["prompt"]], [int(float(spec["seconds"]) * model.fps)], num_samples=1, num_denoising_steps=args.steps,
                       multi_prompt=True, post_processing=True, return_numpy=True)
        single = {k: (v[0] if hasattr(v, "shape") and v.ndim > 0 and v.shape[0] == 1 else v) for k, v in motion.items()}
        stem = args.output / spec["id"]
        save_kimodo_npz(str(stem) + ".npz", single)
        rotations = motion["global_rot_mats"][0]
        positions = motion["posed_joints"][0]
        if not np.isfinite(rotations).all() or not np.isfinite(positions).all():
            raise SystemExit("nonfinite motion: " + spec["id"])
        orthogonal = float(np.max(np.abs(np.swapaxes(rotations, -1, -2) @ rotations - np.eye(3))))
        if orthogonal > 0.005:
            raise SystemExit("invalid rotations: " + spec["id"])
        local = global_rots_to_local_rots(torch.from_numpy(rotations).to(args.device), skeleton)
        save_motion_bvh(str(stem) + ".bvh", local, torch.from_numpy(positions).to(args.device)[:, skeleton.root_idx, :],
                        skeleton=skeleton, fps=model.fps, standard_tpose=True)
        root = positions[:, skeleton.root_idx, :].copy()
        floor = float(positions[:, foot_ids, 1].min()) - 0.025 if foot_ids else float(root[:, 1].min()) - 0.9
        root[:, 1] -= floor
        clip = fmotion_from_global_rotations(spec["id"], spec["kind"], names, rotations.tolist(), root.tolist(), int(model.fps),
                                             region=spec.get("region"), loop=spec.get("loop"),
                                             reference_hip_height=float(np.median(root[:, 1])),
                                             provenance={"source": "Kimodo", "model": model_name, "prompt": spec["prompt"],
                                                         "seed": spec.get("seed"), "steps": args.steps,
                                                         "raw_npz_sha256": digest(str(stem) + ".npz"),
                                                         "licence": "check checkpoint terms (see LICENSE-NOTES.md)"})
        target.write_text(json.dumps(clip) + "\n", encoding="utf-8")
        print("SAVED", spec["id"], round(time.monotonic() - started, 1), flush=True)
    print("FORGE_KIMODO_COMPLETE", len(specs), flush=True)


if __name__ == "__main__":
    main()
