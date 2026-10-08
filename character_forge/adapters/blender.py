"""Headless Blender adapter: `blender --background --factory-startup --python-exit-code 1 --python <script> -- ...`.

Scripts live in <repo>/blender and take explicit input/output paths; they never read machine paths themselves.
"""
from __future__ import annotations

from pathlib import Path

from ..util import ForgeError
from .base import BLENDER_SCRIPTS, run_command


def command(machine, script, args):
    blender = machine.get("blender") or ""
    if not blender:
        raise ForgeError("Blender is not configured; run `forge setup` or use --mode fake")
    script_path = BLENDER_SCRIPTS / script
    if not script_path.is_file():
        raise ForgeError("Missing Blender script " + str(script_path))
    return [blender, "--background", "--factory-startup", "--python-exit-code", "1",
            "--threads", str(int(machine.get("blender_threads") or 4)), "--python", str(script_path), "--", *map(str, args)]


def run(machine, script, args, log_path, expect=(), plan=None, mode="real", timeout=3600):
    result = run_command(command(machine, script, args), log_path, plan=plan, mode=mode, timeout=timeout)
    missing = [str(p) for p in expect if not Path(p).exists()]
    if missing:
        raise ForgeError("Blender script %s exited 0 but did not write: %s (log %s)" % (script, ", ".join(missing), log_path))
    return result


def version(machine):
    import subprocess
    try:
        out = subprocess.run([machine["blender"], "--version"], capture_output=True, text=True, timeout=120).stdout
        return out.splitlines()[0].strip() if out else "unknown"
    except (OSError, subprocess.SubprocessError, KeyError):
        return "unavailable"
