"""Real headless Blender on a generated primitive. Skipped unless FORGE_TEST_BLENDER points at a Blender executable.

  FORGE_TEST_BLENDER=C:/AI/Blender/blender-4.5.14-windows-x64/blender.exe pytest -m blender
"""
import os
from pathlib import Path

import pytest

from character_forge import runner
from character_forge.util import read_json

BLENDER = os.environ.get("FORGE_TEST_BLENDER", "")
pytestmark = [pytest.mark.blender,
              pytest.mark.skipif(not (BLENDER and Path(BLENDER).is_file()), reason="set FORGE_TEST_BLENDER to run real Blender tests")]


def test_real_blender_stages_on_synthetic_primitive(forge):
    assert forge("setup", "--non-interactive", "--set", "blender=" + BLENDER, "--set", "blender_threads=2")[0] == 0
    forge("new", "bl", "--brief", "probe zombie", "--mode", "fake", "--adapter", "blender=real", "--seed", "21")
    code, out = forge.approve_all_and_run("bl")
    assert code == 0, out
    ws = forge.ws("bl")
    rig = ws.stage_dir("rig") / "runs" / runner.current_run(ws, "rig")["run"]
    roundtrip = read_json(rig / "roundtrip.json")
    assert roundtrip["mode"] == "real" and roundtrip["bone_heat_succeeded"]
    assert roundtrip["max_bind_vertex_drift_m"] < 1e-4 and roundtrip["max_bone_head_drift_m"] < 1e-4
    assert not roundtrip["missing_bones_after_import"]
    assert (rig / "bind.fbx").stat().st_size > 10000
    pose = ws.stage_dir("pose-screen") / "runs" / runner.current_run(ws, "pose-screen")["run"]
    assert read_json(pose / "pose-report.json")["blender_pose_agreement_m"] < 1e-3
    assert len(list((pose / "renders").glob("*.png"))) == 8
    motion = ws.stage_dir("motion-screen") / "runs" / runner.current_run(ws, "motion-screen")["run"]
    assert read_json(motion / "blender-agreement.json")["max_bone_head_disagreement_m"] < 1e-3
    package = forge.root / "packages" / "bl"
    assert (package / "bl.fbx").read_bytes()[:18] == b"Kaydara FBX Binary"
    assert read_json(package / "character.manifest.json")["mode"] == "real"
