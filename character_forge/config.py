"""Project root discovery and the per-machine tool configuration written by `forge setup`.

Nothing machine-specific is hardcoded: tool paths live in <root>/config/machine.json (git-ignored).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .util import ForgeError, read_json, write_json

MARKER = "forge-project.json"

DEFAULT_MACHINE = {
    "schema": 1,
    "blender": "",
    "blender_threads": 4,
    "unity": "",
    "unity_project": "unity/SampleProject",
    "kimodo_python": "",
    "kimodo_root": "",
    "kimodo_model": "Kimodo-SOMA-RP-v1.1",
    "kimodo_text_encoder_device": "cpu",
    "lock_root": "",
    "motion_libraries": ["motion-library"],
    "roster_dirs": [],
    "default_mode": "fake",
    "reconstruct": {
        "default_backend": "pixal3d",
        "backends": {
            "pixal3d": {
                "description": "Pixal3D through the trellis.cpp native CLI (MIT code/weights per upstream NOTICE).",
                "command": ["{trellis_cli}", "{reference}", "{output_glb}", "--models", "{models}", "--model", "pixal3d",
                            "--res", "1024", "--atlas", "4096", "--steps", "25", "--seed", "{seed}", "--fov", "30",
                            "--webp", "off", "--require-gpu"],
                "vars": {"trellis_cli": "", "models": ""},
                "gpu": True,
                "licence": "Pixal3D: MIT code/parameters per upstream NOTICE; dependencies separate. Verify before release."
            },
            "trellis2": {
                "description": "TRELLIS.2 flow through the same trellis.cpp CLI (A/B alternative).",
                "command": ["{trellis_cli}", "{reference}", "{output_glb}", "--models", "{models}", "--model", "trellis",
                            "--res", "1024", "--atlas", "4096", "--steps", "25", "--seed", "{seed}", "--require-gpu"],
                "vars": {"trellis_cli": "", "models": ""},
                "gpu": True,
                "licence": "TRELLIS.2: MIT model/code; auxiliary models/renderers separately licensed."
            },
            "hunyuan3d": {
                "description": "Hunyuan3D-2.x local API server (shape+paint). See LICENSE-NOTES.md before shipping outputs.",
                "command": ["{python}", "-m", "character_forge.adapters.hunyuan_client", "--url", "{url}",
                            "--image", "{reference}", "--output", "{output_glb}", "--seed", "{seed}"],
                "vars": {"url": "http://127.0.0.1:8081"},
                "gpu": True,
                "licence": "Tencent Hunyuan 3D Community licence: territory restrictions extend to outputs (EU, UK, South Korea excluded); extra licence above 1M MAU. Not cleared for worldwide shipping by default.",
                "requires_licence_ack": True
            }
        }
    }
}


def find_root(explicit=None) -> Path:
    if explicit:
        root = Path(explicit).resolve()
        if not (root / MARKER).is_file():
            raise ForgeError("%s is not a character-forge project (missing %s)" % (root, MARKER))
        return root
    env = os.environ.get("FORGE_ROOT")
    if env:
        return find_root(env)
    here = Path.cwd().resolve()
    for candidate in [here, *here.parents]:
        if (candidate / MARKER).is_file():
            return candidate
    raise ForgeError("No character-forge project found from %s; run inside the repo, pass --root, or `forge init-project <dir>`." % here)


def init_project(directory) -> Path:
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / MARKER
    if not marker.exists():
        write_json(marker, {"schema": 1, "characters_dir": "characters", "packages_dir": "packages"})
    for sub in ("characters", "packages", "config"):
        (root / sub).mkdir(exist_ok=True)
    return root


def machine_path(root: Path) -> Path:
    return root / "config" / "machine.json"


def _merge(base, override):
    result = dict(base)
    for key, value in (override or {}).items():
        result[key] = _merge(base[key], value) if isinstance(value, dict) and isinstance(base.get(key), dict) else value
    return result


def load_machine(root: Path) -> dict:
    path = machine_path(root)
    data = read_json(path) if path.is_file() else {}
    return _merge(DEFAULT_MACHINE, data)


def save_machine(root: Path, config: dict) -> Path:
    return write_json(machine_path(root), config)


def lock_root(root: Path, config: dict) -> Path:
    value = os.environ.get("FORGE_LOCK_ROOT") or config.get("lock_root") or str(Path.home() / ".character-forge" / "locks")
    return Path(os.path.expanduser(value))


def resolve_path(root: Path, value: str) -> Path:
    path = Path(os.path.expanduser(value))
    return path if path.is_absolute() else root / path


# ---------------------------------------------------------------- setup and doctor

def _candidates_blender():
    hits = []
    which = shutil.which("blender")
    if which:
        hits.append(which)
    for base in (Path("C:/AI/Blender"), Path("C:/Program Files/Blender Foundation"), Path("/Applications/Blender.app/Contents/MacOS"),
                 Path.home() / "blender"):
        if base.is_dir():
            hits += sorted(str(p) for p in base.rglob("blender.exe"))[:3] + sorted(str(p) for p in base.glob("*/blender"))[:3]
            if (base / "Blender").is_file():
                hits.append(str(base / "Blender"))
    return hits


def _candidates_unity():
    hits = []
    for base in (Path("C:/Program Files/Unity/Hub/Editor"), Path("/Applications/Unity/Hub/Editor"), Path.home() / "Unity/Hub/Editor"):
        if base.is_dir():
            for version in sorted(base.iterdir(), reverse=True):
                for exe in (version / "Editor/Unity.exe", version / "Unity.app/Contents/MacOS/Unity", version / "Editor/Unity"):
                    if exe.is_file():
                        hits.append(str(exe))
    return hits


def detect():
    return {"blender": _candidates_blender(), "unity": _candidates_unity()}


def setup(root: Path, assignments=None, interactive=True, ask=input, out=print) -> dict:
    """Write config/machine.json. `assignments` are key=value overrides (dotted keys allowed)."""
    config = load_machine(root)
    found = detect()
    version_file = resolve_path(root, config.get("unity_project", "")) / "ProjectSettings" / "ProjectVersion.txt"
    if version_file.is_file():
        wanted = version_file.read_text(encoding="utf-8").split("m_EditorVersion:")[-1].split()[0]
        found["unity"].sort(key=lambda path: wanted not in path)  # prefer the sample project's editor version
    for key in ("blender", "unity"):
        if not config.get(key) and found[key]:
            config[key] = found[key][0]
    for item in assignments or []:
        if "=" not in item:
            raise ForgeError("Use key=value for --set (got %r)" % item)
        key, value = item.split("=", 1)
        target = config
        parts = key.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    if interactive:
        out("character-forge setup: press Enter to keep the value in [brackets]; '-' clears it.")
        prompts = [("blender", "Blender executable (4.2+)"), ("unity", "Unity Editor executable (6000.x)"),
                   ("unity_project", "Unity project used for import checks"),
                   ("kimodo_python", "Kimodo Python executable (optional)"), ("kimodo_root", "Kimodo checkout (optional)"),
                   ("lock_root", "Shared GPU lock directory (blank = ~/.character-forge/locks)")]
        for key, label in prompts:
            answer = ask("%s [%s]: " % (label, config.get(key, ""))).strip()
            if answer == "-":
                config[key] = ""
            elif answer:
                config[key] = answer
        backends = config["reconstruct"]["backends"]
        for name in ("pixal3d", "trellis2"):
            for var in ("trellis_cli", "models"):
                answer = ask("%s %s [%s]: " % (name, var, backends[name]["vars"].get(var, ""))).strip()
                if answer:
                    backends[name]["vars"][var] = answer
        answer = ask("hunyuan3d server url [%s]: " % backends["hunyuan3d"]["vars"].get("url", "")).strip()
        if answer:
            backends["hunyuan3d"]["vars"]["url"] = answer
        answer = ask("default mode fake|real [%s]: " % config.get("default_mode", "fake")).strip()
        if answer in ("fake", "real"):
            config["default_mode"] = answer
    save_machine(root, config)
    return config


def doctor(root: Path, config: dict):
    rows = []

    def check(name, ok, detail, optional=False):
        rows.append({"check": name, "ok": bool(ok), "optional": optional, "detail": detail})

    check("python", sys.version_info >= (3, 10), sys.version.split()[0])
    for key, optional in (("blender", False), ("unity", True), ("kimodo_python", True)):
        value = config.get(key, "")
        check(key, bool(value) and Path(value).is_file(), value or "not configured", optional)
    project = resolve_path(root, config.get("unity_project", ""))
    check("unity_project", (project / "Packages/manifest.json").is_file(), str(project), True)
    for name, backend in config["reconstruct"]["backends"].items():
        vars_ = backend.get("vars", {})
        exe = vars_.get("trellis_cli")
        if exe is not None:
            check("reconstruct:" + name, bool(exe) and Path(exe).is_file(), exe or "not configured", True)
        elif "url" in vars_:
            check("reconstruct:" + name, bool(vars_["url"]), vars_["url"] + " (server not contacted)", True)
    libraries = [resolve_path(root, p) for p in config.get("motion_libraries", [])]
    check("motion_libraries", any((p / "library.json").is_file() for p in libraries),
          ", ".join(str(p) for p in libraries) + " (create one with `forge library synth`)", True)
    gpu = shutil.which("nvidia-smi")
    check("nvidia-smi", gpu is not None, gpu or "not found (fake mode still works)", True)
    return rows
