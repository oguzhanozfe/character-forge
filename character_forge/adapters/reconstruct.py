"""Image-to-3D reconstruction backends (Pixal3D / TRELLIS.2 via trellis.cpp, Hunyuan3D server) and a fake backend."""
from __future__ import annotations

import sys
from pathlib import Path

from ..lock import held
from ..meshkit.obj import write_obj
from ..meshkit.synth import proportions_from_seed, synthetic_humanoid
from ..util import ForgeError, sha256_file, sha256_json, write_json
from .base import run_command


def fake(out_dir: Path, seed: int, height: float):
    proportions = proportions_from_seed(seed)
    scale = height / proportions.height
    proportions.height = height
    mesh, landmarks = synthetic_humanoid(proportions)
    source = write_obj(mesh, out_dir / "source.obj", header="FAKE reconstruction: synthetic humanoid seed %d" % seed)
    write_json(out_dir / "source-landmarks.json", {"format": "character-forge/landmarks@1", "origin": "fake backend (exact)",
                                                  "landmarks": {k: list(v) for k, v in landmarks.items()}})
    return {"mesh": source, "landmarks": out_dir / "source-landmarks.json",
            "receipt": {"backend": "fake", "seed": seed, "proportions": vars(proportions), "scale_hint": scale}}


def real(machine, backend_name, reference: Path, out_dir: Path, seed: int, log_path: Path, lock_dir: Path, owner: str,
         plan=None, mode="real", licence_ack=()):
    backends = machine["reconstruct"]["backends"]
    if backend_name not in backends:
        raise ForgeError("Unknown reconstruction backend %r (configured: %s)" % (backend_name, ", ".join(backends)))
    backend = backends[backend_name]
    if backend.get("requires_licence_ack") and backend_name not in licence_ack:
        raise ForgeError("Backend %s needs an explicit licence acknowledgement: %s\nAdd \"%s\" to params.licence_ack in "
                         "character.json only after reading LICENSE-NOTES.md." % (backend_name, backend.get("licence"), backend_name))
    output = out_dir / "source.glb"
    values = dict(backend.get("vars", {}), reference=str(reference), output_glb=str(output), seed=str(seed),
                  python=sys.executable, out_dir=str(out_dir))
    missing = [k for k, v in values.items() if v == ""]
    if missing and mode == "dry-run":
        values.update({k: "<unset:%s>" % k for k in missing})
    elif missing:
        raise ForgeError("Backend %s is missing configuration: %s (run `forge setup`)" % (backend_name, ", ".join(missing)))
    try:
        command = [part.format(**values) for part in backend["command"]]
    except KeyError as error:
        raise ForgeError("Backend %s command uses unknown variable %s" % (backend_name, error))
    if mode == "dry-run" or not backend.get("gpu"):
        result = run_command(command, log_path, plan=plan, mode=mode, timeout=7200)
    else:
        with held(lock_dir, "gpu", owner, timeout=6 * 3600):
            result = run_command(command, log_path, plan=plan, mode=mode, timeout=7200)
    if not output.is_file():
        raise ForgeError("Backend %s finished but wrote no %s (log %s)" % (backend_name, output, log_path))
    receipt = {"backend": backend_name, "seed": seed, "command": command, "reference_sha256": sha256_file(reference),
               "output_sha256": sha256_file(output), "seconds": result["seconds"], "licence": backend.get("licence", ""),
               "backend_config_sha256": sha256_json(backend)}
    exe = Path(command[0])
    if exe.is_file():
        receipt["executable_sha256"] = sha256_file(exe)
    return {"mesh": output, "landmarks": None, "receipt": receipt}
