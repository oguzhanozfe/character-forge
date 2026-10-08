"""Stage runner: resume by input hash, staleness propagation, tamper detection, failures, approvals binding."""
import json

import pytest

from character_forge import approvals, runner
from character_forge.util import ForgeError, read_json


def make(forge, identifier="w1", policy="human", mode="fake"):
    forge("new", identifier, "--brief", "Lanky orderly zombie with a torn smock", "--mode", mode, "--review-policy", policy)
    return forge.ws(identifier)


def states(ws):
    return {name: entry["state"] for name, entry in runner.evaluate(ws).items()}


def test_resume_reuses_unchanged_runs(forge):
    ws = make(forge)
    forge.approve_all_and_run("w1")
    first = {s: runner.current_run(ws, s)["run"] for s in runner.ORDER}
    assert runner.run(ws, log=lambda *_: None) == 0
    assert {s: runner.current_run(ws, s)["run"] for s in runner.ORDER} == first
    assert set(states(ws).values()) <= {"approved", "done"}


def test_changed_parameter_makes_stage_and_downstream_stale(forge):
    ws = make(forge)
    forge.approve_all_and_run("w1")
    data = ws.load()
    data["params"]["triangle_budget"] = 50000          # lowmesh parameter
    ws.save(data)
    s = states(ws)
    assert s["reference"] == "approved" and s["preflight"] == "approved"
    assert s["lowmesh"] == "stale"
    assert all(s[n] == "blocked" for n in ("rig", "pose-screen", "unity-import", "motion-screen", "package"))
    # rerun: lowmesh gets a new hash; rig output is byte-identical, so pose-screen keeps its approval
    code, out = forge("run", "w1")
    assert code == 0, out
    assert states(ws)["pose-screen"] == "approved"


def test_changed_seed_invalidates_approvals_downstream(forge):
    ws = make(forge)
    forge.approve_all_and_run("w1")
    data = ws.load()
    data["params"]["seed"] = 999
    ws.save(data)
    code, out = forge("run", "w1")
    assert code == 3 and "preflight" in out            # new geometry -> preflight needs a fresh approval
    assert states(ws)["preflight"] == "awaiting-approval"
    assert approvals.effective(ws, "preflight", runner.current_run(ws, "preflight")["run"], "x", "human")[0] == "stale"


def test_modified_output_is_detected(forge):
    ws = make(forge)
    forge("run", "w1")
    forge("approve", "w1", "--stage", "reference", "--by", "human", "--note", "ok")
    forge("run", "w1")
    record = runner.current_run(ws, "reconstruct")
    mesh = ws.dir / record["outputs"]["mesh"]["path"]
    mesh.write_text(mesh.read_text() + "\n# tampered\n")
    assert states(ws)["reconstruct"] == "modified"
    code, _ = forge("run", "w1", "--until", "reconstruct")
    assert code == 0 and states(ws)["reconstruct"] == "done"
    superseded = [p.name for p in (ws.stage_dir("reconstruct") / "runs").iterdir() if "superseded" in p.name]
    assert superseded, "previous attempt must be kept, not overwritten"


def test_failed_stage_is_recorded_and_retried(forge, monkeypatch):
    ws = make(forge)
    forge("run", "w1")
    forge("approve", "w1", "--stage", "reference", "--by", "human", "--note", "ok")
    from character_forge.stages import reconstruct

    def boom(*args, **kwargs):
        raise ForgeError("backend exploded")

    monkeypatch.setattr(reconstruct.adapter, "fake", boom)
    code, out = forge("run", "w1")
    assert code == 1 and "backend exploded" in out
    assert states(ws)["reconstruct"] == "failed"
    monkeypatch.undo()
    monkeypatch.setenv("FORGE_LOCK_ROOT", str(forge.root / "locks"))
    code, out = forge("run", "w1")
    assert code == 3 and states(ws)["reconstruct"] == "done"


def test_unexpected_exception_keeps_traceback(forge, monkeypatch):
    ws = make(forge)
    forge("run", "w1")
    forge("approve", "w1", "--stage", "reference", "--by", "human", "--note", "ok")
    from character_forge.stages import reconstruct
    monkeypatch.setattr(reconstruct.adapter, "fake", lambda *a, **k: 1 / 0)
    assert forge("run", "w1")[0] == 1
    run_dir = ws.stage_dir("reconstruct") / "runs" / runner.current_run(ws, "reconstruct")["run"]
    assert "ZeroDivisionError" in (run_dir / "traceback.txt").read_text()


def test_agent_approval_is_advisory_under_human_policy(forge):
    ws = make(forge, policy="human")
    forge("run", "w1")
    code, out = forge("approve", "w1", "--stage", "reference", "--by", "agent", "--note", "looks fine")
    assert "advisory" in out
    assert states(ws)["reference"] == "awaiting-approval"
    assert runner.evaluate(ws)["reference"]["approval"] == "advisory"
    forge("approve", "w1", "--stage", "reference", "--by", "human", "--note", "owner: ok")
    assert states(ws)["reference"] == "approved"


def test_agent_policy_lets_agent_approve(forge):
    ws = make(forge, identifier="a1", policy="agent")
    code, out = forge.approve_all_and_run("a1", by="agent")
    assert code == 0, out
    records = read_json(ws.approvals_path())["records"]
    assert records and all(r["by"] == "agent" for r in records)


def test_rejection_blocks_until_inputs_change(forge):
    ws = make(forge)
    forge("run", "w1")
    forge("reject", "w1", "--stage", "reference", "--by", "agent", "--note", "hands touch thighs")
    assert states(ws)["reference"] == "rejected"
    code, out = forge("run", "w1")
    assert code == 3 and "rejected" in out
    forge("approve", "w1", "--stage", "reference", "--by", "human", "--note", "owner overrides: fine for a test")
    assert states(ws)["reference"] == "approved"


def test_failed_gate_needs_human_waiver(forge):
    ws = make(forge, mode="real")
    data = ws.load()
    data["adapters"] = {"reconstruct": "dry-run"}
    ws.save(data)
    code, out = forge("run", "w1")
    assert code == 1 and states(ws)["reference"] == "gate-failed"
    code, out = forge("approve", "w1", "--stage", "reference", "--by", "human", "--note", "x")
    assert code == 2 and "FAILED" in out
    code, out = forge("approve", "w1", "--stage", "reference", "--by", "agent", "--note", "x", "--waive-failures")
    assert code == 2 and "Only a human" in out
    code, out = forge("approve", "w1", "--stage", "reference", "--by", "human", "--note", "waived for test", "--waive-failures")
    assert code == 0
    assert states(ws)["reference"] == "approved"
    assert read_json(ws.approvals_path())["records"][-1]["waived_failures"] is True


def test_regate_keeps_approval_when_report_is_unchanged(forge):
    ws = make(forge)
    forge("run", "w1")
    forge("approve", "w1", "--stage", "reference", "--by", "human", "--note", "ok")
    before = read_json(ws.stage_dir("reference") / "runs" / runner.current_run(ws, "reference")["run"] / "gate.json")
    gate = runner.regate(ws, "reference")
    assert json.dumps(gate, sort_keys=True) == json.dumps(before, sort_keys=True)
    assert states(ws)["reference"] == "approved"


def test_unknown_stage_rejected(forge):
    ws = make(forge)
    with pytest.raises(ForgeError):
        runner.run(ws, only="sculpt")


def test_dry_run_plans_without_outputs(forge, png_file):
    ws = make(forge, mode="dry-run")
    forge("add-reference", "w1", str(png_file), "--provenance", "test")
    forge("run", "w1")
    forge("approve", "w1", "--stage", "reference", "--by", "human", "--note", "ok")
    code, out = forge("run", "w1")
    assert code == 3 and "dry-run: planned only" in out
    record = runner.current_run(ws, "reconstruct")
    assert record["status"] == "planned" and record["plan"][0]["command"]
    assert states(ws)["reconstruct"] == "planned"
