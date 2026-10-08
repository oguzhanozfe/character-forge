import json

from character_forge import packaging
from character_forge.util import read_json


def test_presets_and_version(forge):
    code, out = forge("presets")
    assert code == 0 and "zombie" in out and "humanoid" in out


def test_new_validates_ids_and_preserves_existing(forge):
    assert forge("new", "Bad Id", "--brief", "x")[0] == 2
    assert forge("new", "z1", "--brief", "a zombie", "--mode", "fake")[0] == 0
    code, out = forge("new", "z1", "--brief", "again")
    assert code == 2 and "already exists" in out
    assert forge("new", "z2", "--brief", "   ")[0] == 2
    assert forge("new", "z3", "--brief", "x", "--preset", "dragon")[0] == 2


def test_new_writes_brief_from_template(forge):
    forge("new", "z1", "--brief", "Stocky dock worker {not a format field}", "--mode", "fake")
    text = (forge.ws("z1").dir / "brief.md").read_text(encoding="utf-8")
    assert "Stocky dock worker {not a format field}" in text and "Identity checklist" in text


def test_full_fake_pipeline_end_to_end(forge):
    assert forge("new", "demo", "--brief", "Gaunt pump attendant zombie in a torn oilskin coat", "--mode", "fake")[0] == 0
    code, out = forge.approve_all_and_run("demo")
    assert code == 0, out
    code, out = forge("status", "demo")
    assert code == 0
    for stage in ("reference", "preflight", "pose-screen", "unity-import", "motion-screen"):
        assert any(line.split()[:2] == [stage, "approved"] for line in out.splitlines()), out
    package = forge.root / "packages" / "demo"
    assert packaging.verify(package, "demo", 350)
    manifest = read_json(package / "character.manifest.json")
    assert manifest["mode"] == "fake"
    assert len(manifest["humanoid"]) == 52 and len(manifest["hitboxes"]) == 20 and len(manifest["gore"]) == 9
    assert {m["kind"] for m in manifest["motions"]} == {"Idle", "Walk", "Run", "Attack", "Death", "Hit"}
    receipt = read_json(package / "receipt.json")
    assert set(receipt["stages"]) == {"reference", "reconstruct", "preflight", "lowmesh", "rig", "pose-screen", "unity-import", "motion-screen"}
    assert all(name in receipt["files"] for name in ("demo.fbx", "character.manifest.json"))
    # a second run reuses everything
    code, out = forge("run", "demo")
    assert code == 0 and out.count("up-to-date") == 9


def test_show_gate_and_render(forge):
    forge("new", "demo", "--brief", "zombie", "--mode", "fake")
    forge.approve_all_and_run("demo")
    code, out = forge("show", "demo", "--stage", "preflight")
    assert code == 0 and "review before approving" in out and "preview" in out
    code, out = forge("gate", "demo", "--render")
    assert code == 0 and "contact sheet" in out
    gates = forge.ws("demo").dir / "gates"
    summary = read_json(gates / "summary.json")
    assert [s["stage"] for s in summary["stages"]][0] == "reference"
    assert (gates / "summary.csv").read_text().startswith("stage,state,status")
    request = read_json(gates / "contact-sheet-request.json")
    assert any(v["kind"] == "pose" for v in request["views"])
    assert (gates / "contact-sheet.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    code, out = forge("gate", "demo", "--json")
    assert json.loads(out)["character"] == "demo"


def test_add_reference_and_reference_gate(forge, png_file):
    forge("new", "r1", "--brief", "zombie", "--mode", "real", "--adapter", "reconstruct=dry-run")
    code, out = forge("run", "r1")
    assert code == 1 and "front_reference_present" in out  # real mode without a reference: FAIL
    assert forge("add-reference", "r1", str(png_file), "--view", "front", "--provenance", "test render, owned")[0] == 0
    assert forge("add-reference", "r1", str(png_file), "--view", "front")[0] == 2  # no silent replacement
    code, out = forge("run", "r1")
    assert code == 3 and "awaiting" in out
    forge("approve", "r1", "--stage", "reference", "--by", "human", "--note", "ok")
    code, out = forge("run", "r1")
    assert code == 3 and "would run" in out and "--model" in out  # dry-run plan of the reconstruction command


def test_approve_requires_completed_run_and_note(forge):
    forge("new", "a1", "--brief", "zombie", "--mode", "fake")
    code, out = forge("approve", "a1", "--stage", "preflight", "--by", "human", "--note", "x")
    assert code == 2 and "blocked" in out
    forge("run", "a1")
    code, out = forge("approve", "a1", "--stage", "reference", "--by", "human", "--note", " ")
    assert code == 2


def test_setup_doctor_and_library_commands(forge):
    code, out = forge("setup", "--non-interactive", "--set", "blender_threads=2", "--set", "reconstruct.default_backend=trellis2")
    assert code == 0
    data = read_json(forge.root / "config" / "machine.json")
    assert data["blender_threads"] == "2" and data["reconstruct"]["default_backend"] == "trellis2"
    code, out = forge("doctor")
    assert "python" in out
    code, out = forge("library", "synth", "--hits")
    assert code == 0
    code, out = forge("library", "list")
    assert "Proc_Walk_01" in out and "Proc_Hit_LeftHand_01" in out


def test_library_clips_are_used_before_generation(forge):
    forge("library", "synth")
    forge("new", "l1", "--brief", "zombie", "--mode", "fake")
    assert forge.approve_all_and_run("l1")[0] == 0
    run = forge.ws("l1").stage_dir("motion-screen") / "runs"
    plan = read_json(next(run.iterdir()) / "motion-plan.json")
    sources = {c["slot"][0]: c["library"] for c in plan["clips"]}
    assert sources["Walk"] == "procedural-starter"          # from the shared library
    assert sources["Hit"].startswith("generated:")          # library lacks a chest hit -> generated
    assert [g["kind"] for g in plan["generated"]] == ["Hit"]


def test_clean_keeps_current_runs(forge):
    forge("new", "c1", "--brief", "zombie", "--mode", "fake")
    forge.approve_all_and_run("c1")
    assert forge("run", "c1", "--stage", "rig", "--force")[0] == 0
    stage_runs = forge.ws("c1").stage_dir("rig") / "runs"
    assert len(list(stage_runs.iterdir())) == 2
    code, out = forge("clean", "c1")
    assert code == 0 and len(list(stage_runs.iterdir())) == 1
