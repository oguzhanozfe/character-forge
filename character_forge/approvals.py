"""Approval records bound to the exact stage run (input hash) and gate report bytes.

Rerunning a stage or changing its gate report makes an earlier approval stale automatically.
Agent approvals unblock a stage only when the character's review_policy is "agent"; otherwise they are advisory.
"""
from __future__ import annotations

from .util import ForgeError, now, read_json, write_json

DECISIONS = ("approved", "rejected")


def load(ws):
    path = ws.approvals_path()
    return read_json(path) if path.is_file() else {"format": "character-forge/approvals@1", "records": []}


def record(ws, stage, decision, by, note, reviewer="", waive_failures=False):
    from .runner import evaluate
    if decision not in DECISIONS:
        raise ForgeError("decision must be approved or rejected")
    if by not in ("human", "agent"):
        raise ForgeError("--by must be human or agent")
    if not note or not note.strip():
        raise ForgeError("A note is required: say what was inspected (views, reports) and what remains open.")
    state = evaluate(ws).get(stage)
    if state is None:
        raise ForgeError("Unknown stage %s" % stage)
    if state["state"] in ("blocked", "not-run", "stale", "failed", "planned", "modified"):
        raise ForgeError("Stage %s is %s%s; only a current, completed run can be reviewed." % (
            stage, state["state"], (" (" + state["reason"] + ")") if state.get("reason") else ""))
    current = state["run"]
    gate = read_json(ws.stage_dir(stage) / "runs" / current["run"] / "gate.json")
    if decision == "approved" and gate["status"] == "FAIL":
        if not waive_failures:
            raise ForgeError("Gate %s FAILED (%d failing checks). Fix and rerun, or a human may approve with "
                             "--waive-failures and a note explaining why." % (stage, gate["counts"]["FAIL"]))
        if by != "human":
            raise ForgeError("Only a human can waive failing checks.")
    from .gates import gate_hash
    data = load(ws)
    entry = {"stage": stage, "run": current["run"], "input_hash": current["input_hash"],
             "gate_sha256": gate_hash(ws.stage_dir(stage) / "runs" / current["run"]), "gate_status": gate["status"],
             "decision": decision, "by": by, "reviewer": reviewer or by, "note": note.strip(),
             "waived_failures": bool(waive_failures and decision == "approved"), "utc": now()}
    data["records"].append(entry)
    write_json(ws.approvals_path(), data)
    return entry


def latest(ws, stage, run=None):
    records = [r for r in load(ws)["records"] if r["stage"] == stage and (run is None or r["run"] == run)]
    return records[-1] if records else None


def effective(ws, stage, run, gate_sha, policy):
    """Return (state, record): state in approved|rejected|advisory|stale|none."""
    records = [r for r in load(ws)["records"] if r["stage"] == stage]
    if not records:
        return "none", None
    matching = [r for r in records if r["run"] == run and r["gate_sha256"] == gate_sha]
    if not matching:
        return "stale", records[-1]
    # A rejection always blocks (blocking is safe); an agent approval counts only under review_policy "agent".
    authoritative = [r for r in matching if r["by"] == "human" or policy == "agent" or r["decision"] == "rejected"]
    if not authoritative:
        return "advisory", matching[-1]
    r = authoritative[-1]
    return ("approved" if r["decision"] == "approved" else "rejected"), r
