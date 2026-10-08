"""Unity batchmode adapter (import a candidate, build the Humanoid Avatar, hitboxes and gore regions, report)
and a fake twin that validates the same contract from the interchange data."""
from __future__ import annotations

import shutil
from pathlib import Path

from ..config import resolve_path
from ..lock import held
from ..util import ForgeError, read_json, write_json
from .base import run_command

EXECUTE = "CharacterForge.Editor.ForgeBatch.ImportCandidate"


def fake(candidate: Path, report_path: Path, preset_required, hit_regions, gore_regions):
    manifest = read_json(candidate / "character.manifest.json")
    mapped = {row["human"]: row["bone"] for row in manifest.get("humanoid", [])}
    missing = [b for b in preset_required if b not in mapped]
    report = {"format": "character-forge/unity-import-report@1", "mode": "fake", "unity_version": "fake",
              "character": manifest["id"], "avatar_valid": not missing, "avatar_human": not missing,
              "mapped_human_bones": len(mapped), "missing_required_bones": missing,
              "hitboxes": len(manifest.get("hitboxes", [])), "hitbox_regions": sorted(h["region"] for h in manifest.get("hitboxes", [])),
              "gore_regions": len(manifest.get("gore", [])), "expected_hitboxes": len(hit_regions),
              "expected_gore_regions": len(gore_regions), "materials": len(manifest.get("materials", [])),
              "prefab": "fake://" + manifest["id"] + ".prefab", "errors": [],
              "note": "FAKE: contract checked from the manifest only; no Unity import happened."}
    write_json(report_path, report)
    return report


def real(machine, root: Path, candidate: Path, character_id: str, report_path: Path, log_path: Path, lock_dir: Path,
         owner: str, plan=None, mode="real"):
    unity = machine.get("unity") or ""
    project = resolve_path(root, machine.get("unity_project", "unity/SampleProject"))
    if mode != "dry-run":
        if not unity:
            raise ForgeError("Unity is not configured; run `forge setup` or use fake mode for unity-import")
        if not (project / "Packages/manifest.json").is_file():
            raise ForgeError("Unity project not found: %s" % project)
    target = project / "Assets" / "CharacterForge" / "Candidates" / character_id
    command = [unity or "Unity", "-batchmode", "-quit", "-projectPath", str(project), "-executeMethod", EXECUTE,
               "-forgeCandidate", "Assets/CharacterForge/Candidates/" + character_id, "-forgeReport", str(report_path),
               "-logFile", str(log_path.with_suffix(".unity.log"))]
    if mode == "dry-run":
        run_command(command, log_path, plan=plan, mode=mode)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(candidate, target)
    # One Unity batch process at a time on a shared machine.
    with held(lock_dir, "unity-batch", owner, timeout=3 * 3600):
        run_command(command, log_path, timeout=3 * 3600)
    if not report_path.is_file():
        raise ForgeError("Unity exited without writing %s (see %s)" % (report_path, log_path.with_suffix(".unity.log")))
    return read_json(report_path)
