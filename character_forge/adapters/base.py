"""Mode resolution and a logged subprocess runner shared by all adapters."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from ..util import ForgeError, now

MODES = ("fake", "real", "dry-run")
ADAPTER_KINDS = ("reconstruct", "blender", "kimodo", "unity")
REPO = Path(__file__).resolve().parents[2]
BLENDER_SCRIPTS = REPO / "blender"
KIMODO_SCRIPTS = REPO / "kimodo"


def resolve_mode(character, kind, override=None):
    mode = override or (character.get("adapters") or {}).get(kind) or character.get("mode") or "fake"
    if mode not in MODES:
        raise ForgeError("Unknown mode %r for adapter %s (use fake, real or dry-run)" % (mode, kind))
    return mode


class Planned(Exception):
    """Raised by adapters in dry-run mode after recording the command they would run."""


def run_command(command, log_path, cwd=None, env=None, timeout=None, plan=None, mode="real"):
    """Run a command, streaming combined output to log_path. In dry-run mode, record and raise Planned."""
    command = [str(c) for c in command]
    if mode == "dry-run":
        if plan is not None:
            plan.append({"command": command, "cwd": str(cwd) if cwd else None, "log": str(log_path)})
        raise Planned(" ".join(command))
    if not Path(command[0]).is_file() and command[0] != sys.executable:
        raise ForgeError("Configured executable not found: %s (run `forge setup`)" % command[0])
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    full_env = dict(os.environ, **(env or {}))
    with log_path.open("wb") as log:
        log.write(("# %s\n# %s\n" % (now(), " ".join(command))).encode("utf-8"))
        log.flush()
        try:
            process = subprocess.run(command, cwd=cwd, env=full_env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ForgeError("Command timed out after %ss: %s (see %s)" % (timeout, command[0], log_path))
    elapsed = time.monotonic() - started
    if process.returncode != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
        raise ForgeError("Command failed (exit %d after %.1fs): %s\n  log: %s\n  %s" % (
            process.returncode, elapsed, Path(command[0]).name, log_path, "\n  ".join(tail)))
    return {"command": command, "exit_code": 0, "seconds": round(elapsed, 2), "log": str(log_path)}
