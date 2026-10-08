"""Adapters in fake and dry-run modes, command construction and licence guards."""
import py_compile
from pathlib import Path

import pytest

from character_forge import config
from character_forge.adapters import base, blender, kimodo, reconstruct, unity
from character_forge.meshkit.obj import read_obj
from character_forge.util import ForgeError, read_json, sha256_file, write_json

REPO = Path(__file__).resolve().parents[1]


def test_fake_reconstruction_is_deterministic_and_seed_dependent(tmp_path):
    a = reconstruct.fake(tmp_path / "a", 7, 1.8)
    b = reconstruct.fake(tmp_path / "b", 7, 1.8)
    c = reconstruct.fake(tmp_path / "c", 8, 1.8)
    assert sha256_file(a["mesh"]) == sha256_file(b["mesh"]) != sha256_file(c["mesh"])
    mesh = read_obj(a["mesh"])
    assert len(mesh.vertices) > 1000 and read_json(a["landmarks"])["landmarks"]["LeftHand"]


def test_real_reconstruction_guards(tmp_path):
    machine = config.load_machine(tmp_path)
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"\x89PNG")
    with pytest.raises(ForgeError, match="licence acknowledgement"):
        reconstruct.real(machine, "hunyuan3d", ref, tmp_path, 1, tmp_path / "log", tmp_path / "locks", "t")
    with pytest.raises(ForgeError, match="missing configuration"):
        reconstruct.real(machine, "pixal3d", ref, tmp_path, 1, tmp_path / "log", tmp_path / "locks", "t")
    with pytest.raises(ForgeError, match="Unknown reconstruction backend"):
        reconstruct.real(machine, "nope", ref, tmp_path, 1, tmp_path / "log", tmp_path / "locks", "t")
    plan = []
    with pytest.raises(base.Planned):
        reconstruct.real(machine, "pixal3d", ref, tmp_path, 1, tmp_path / "log", tmp_path / "locks", "t", plan=plan, mode="dry-run")
    command = plan[0]["command"]
    assert "--model" in command and command[command.index("--model") + 1] == "pixal3d" and str(ref) in command


def test_blender_command_is_headless_and_fails_fast():
    cmd = blender.command({"blender": "/opt/blender/blender", "blender_threads": 3}, "preflight.py", ["--source", "x.glb"])
    assert cmd[:6] == ["/opt/blender/blender", "--background", "--factory-startup", "--python-exit-code", "1", "--threads"]
    assert cmd[cmd.index("--") + 1:] == ["--source", "x.glb"]
    with pytest.raises(ForgeError, match="not configured"):
        blender.command({"blender": ""}, "preflight.py", [])
    with pytest.raises(ForgeError, match="Missing Blender script"):
        blender.command({"blender": "b"}, "nope.py", [])


def test_run_command_reports_missing_executable_and_failures(tmp_path):
    with pytest.raises(ForgeError, match="not found"):
        base.run_command([str(tmp_path / "missing.exe")], tmp_path / "log")
    import sys
    result = base.run_command([sys.executable, "-c", "print('hello')"], tmp_path / "ok.log")
    assert result["exit_code"] == 0 and "hello" in (tmp_path / "ok.log").read_text()
    with pytest.raises(ForgeError, match="exit 3"):
        base.run_command([sys.executable, "-c", "import sys; sys.exit(3)"], tmp_path / "bad.log")


def test_kimodo_fake_and_dry_run(tmp_path):
    requests = [{"id": "z_Walk_01", "kind": "Walk", "prompt": "walk", "seconds": 2, "seed": 1},
                {"id": "z_Hit_Head_01", "kind": "Hit", "region": "Head", "prompt": "hit", "seconds": 1, "seed": 2}]
    files = kimodo.fake(requests, tmp_path / "gen", 0.9)
    clip = read_json(files[1])
    assert clip["format"] == "character-forge/motion@1" and clip["region"] == "Head"
    assert clip["provenance"]["requested_prompt"] == "hit"
    plan = []
    with pytest.raises(base.Planned):
        kimodo.real({"kimodo_model": "Kimodo-SOMA-RP-v1.1"}, requests, tmp_path / "k", tmp_path / "k.log", tmp_path / "locks", "t",
                    plan=plan, mode="dry-run")
    assert "generate_motions.py" in " ".join(plan[0]["command"])
    assert read_json(tmp_path / "k" / "queue.json")["candidates"][0]["id"] == "z_Walk_01"
    with pytest.raises(ForgeError, match="not configured"):
        kimodo.real({}, requests, tmp_path / "k2", tmp_path / "k.log", tmp_path / "locks", "t")


def test_unity_fake_report_checks_contract(tmp_path):
    candidate = tmp_path / "cand"
    write_json(candidate / "character.manifest.json", {"id": "u", "humanoid": [{"human": "Hips", "bone": "Hips"}],
                                                       "hitboxes": [{"region": "Head"}], "gore": [], "materials": []})
    report = unity.fake(candidate, tmp_path / "r.json", ["Hips", "Head"], ["Head"], [])
    assert report["avatar_valid"] is False and report["missing_required_bones"] == ["Head"]
    assert report["mode"] == "fake"


def test_unity_dry_run_command(tmp_path):
    plan = []
    project = tmp_path / "proj"
    with pytest.raises(base.Planned):
        unity.real({"unity": "", "unity_project": str(project)}, tmp_path, tmp_path / "cand", "u", tmp_path / "r.json",
                   tmp_path / "u.log", tmp_path / "locks", "t", plan=plan, mode="dry-run")
    command = plan[0]["command"]
    assert "-batchmode" in command and unity.EXECUTE in command and "-forgeReport" in command


def test_mode_resolution():
    character = {"mode": "real", "adapters": {"unity": "fake"}}
    assert base.resolve_mode(character, "unity") == "fake"
    assert base.resolve_mode(character, "blender") == "real"
    assert base.resolve_mode(character, "unity", override="dry-run") == "dry-run"
    with pytest.raises(ForgeError):
        base.resolve_mode({"mode": "turbo"}, "blender")


@pytest.mark.parametrize("script", sorted((REPO / "blender").glob("*.py")) + [REPO / "kimodo" / "generate_motions.py"],
                         ids=lambda p: p.name)
def test_external_scripts_compile(script, tmp_path):
    py_compile.compile(str(script), cfile=str(tmp_path / "x.pyc"), doraise=True)


def test_hunyuan_client_rejects_non_gltf(tmp_path, monkeypatch):
    from character_forge.adapters import hunyuan_client

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"<html>error</html>"

    monkeypatch.setattr(hunyuan_client.urllib.request, "urlopen", lambda *a, **k: Response())
    image = tmp_path / "i.png"
    image.write_bytes(b"\x89PNG")
    assert hunyuan_client.main(["--url", "http://x", "--image", str(image), "--output", str(tmp_path / "o.glb")]) == 2
