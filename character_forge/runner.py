"""Resumable stage runner. Each stage run lives in stages/<stage>/runs/<hash12>/ where the hash covers the stage
version, adapter mode, parameters, the bytes of every input (upstream outputs, references, libraries) and the
stage's own tool code. Unchanged inputs are reused; any change creates a fresh run and makes later stages stale.
Runs are never overwritten: superseded or failed attempts are moved aside, not deleted."""
from __future__ import annotations

import inspect
import shutil
import time
import traceback
from pathlib import Path

from . import approvals
from .adapters.base import REPO, Planned, resolve_mode
from .gates import gate_hash
from .stages import BY_NAME, ORDER, STAGES
from .stages.base import Context
from .util import ForgeError, now, read_json, sha256_file, sha256_json, write_json

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_WAITING = 0, 1, 2, 3
SATISFIED = ("approved", "done")


def stage_mode(character, stage, override=None):
    return "python" if stage.adapter == "python" else resolve_mode(character, stage.adapter, override)


def current_run(ws, stage_name):
    pointer = ws.stage_dir(stage_name) / "current.json"
    if not pointer.is_file():
        return None
    run = read_json(pointer)["run"]
    record = ws.stage_dir(stage_name) / "runs" / run / "run.json"
    return read_json(record) if record.is_file() else None


def _tool_hash(stage):
    files = [Path(inspect.getfile(type(stage)))] + [REPO / f for f in stage.tool_files]
    return sha256_json({f.name: (sha256_file(f) if f.is_file() else "missing") for f in files})


def _file_record(path: Path, base: Path):
    stat = path.stat()
    try:
        rel = path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        rel = str(path.resolve())
    return {"path": rel, "sha256": sha256_file(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _resolve(ws, record_path):
    p = Path(record_path)
    return p if p.is_absolute() else ws.dir / p


def _outputs_intact(ws, record):
    for out in record.get("outputs", {}).values():
        path = _resolve(ws, out["path"])
        if not path.exists():
            return False
        if path.is_file():
            stat = path.stat()
            if stat.st_size != out["bytes"] or (stat.st_mtime_ns != out["mtime_ns"] and sha256_file(path) != out["sha256"]):
                return False
    return True


def evaluate(ws, mode_override=None):
    """State of every stage, in order. States: blocked, not-run, stale, failed, planned, modified, gate-failed,
    awaiting-approval, rejected, approved, done."""
    character = ws.load()
    preset = ws.preset
    machine = ws.machine
    required = set(preset.get("approvals", []))
    policy = character.get("review_policy", "human")
    info = {}
    for stage in STAGES:
        entry = {"stage": stage.name, "title": stage.title, "needs_approval": stage.name in required}
        info[stage.name] = entry
        blockers = ["%s is %s" % (n, info[n]["state"]) for n in stage.needs if info[n]["state"] not in SATISFIED]
        if blockers:
            entry.update(state="blocked", reason="; ".join(blockers))
            continue
        mode = stage_mode(character, stage, mode_override)
        inputs = {}
        upstream = {}
        for need in stage.needs:
            record = info[need]["run"]
            upstream[need] = record
            for label, out in record["outputs"].items():
                inputs["%s.%s" % (need, label)] = _resolve(ws, out["path"])
        for label, path in stage.extra_inputs(ws, character, machine).items():
            inputs[label] = Path(path)
        params = stage.params(ws, character, preset, machine)
        input_hashes = {}
        for label, path in sorted(inputs.items()):
            if path.is_file():
                input_hashes[label] = sha256_file(path)
            elif path.is_dir():
                input_hashes[label] = sha256_json({p.relative_to(path).as_posix(): sha256_file(p) for p in sorted(path.rglob("*")) if p.is_file()})
            else:
                input_hashes[label] = "missing"
        digest = sha256_json({"stage": stage.name, "version": stage.version, "mode": mode, "params": params,
                              "inputs": input_hashes, "tool": _tool_hash(stage)})
        entry.update(mode=mode, inputs=inputs, upstream=upstream, params=params, input_hash=digest, run_id=digest[:12])
        record = current_run(ws, stage.name)
        entry["run"] = record
        if record is None:
            entry["state"] = "not-run"
        elif record["input_hash"] != digest:
            entry["state"] = "stale"
            entry["reason"] = "inputs, parameters, mode or tool code changed since run %s" % record["run"]
        elif record["status"] == "failed":
            entry.update(state="failed", reason=record.get("error", ""))
        elif record["status"] == "planned":
            entry["state"] = "planned"
        elif record["status"] != "done":
            entry["state"] = "failed"
            entry["reason"] = "incomplete run (%s)" % record["status"]
        elif not _outputs_intact(ws, record):
            entry.update(state="modified", reason="outputs changed or missing after the run")
        else:
            run_dir = ws.stage_dir(stage.name) / "runs" / record["run"]
            gate = read_json(run_dir / "gate.json")
            entry["gate"] = gate["status"]
            decision, approval = approvals.effective(ws, stage.name, record["run"], gate_hash(run_dir), policy)
            entry["approval"] = decision
            entry["approval_record"] = approval
            if decision == "rejected":
                entry.update(state="rejected", reason=approval["note"])
            elif gate["status"] == "FAIL" and not (decision == "approved" and approval.get("waived_failures")):
                entry["state"] = "gate-failed"
                entry["reason"] = "; ".join("%s: %s" % (c["id"], c["message"]) for c in gate["checks"] if c["status"] == "FAIL")[:600]
            elif stage.name in required and decision != "approved":
                entry["state"] = "awaiting-approval"
                if decision == "advisory":
                    entry["reason"] = "agent review recorded; review_policy=human needs a human approval"
            else:
                entry["state"] = "approved" if stage.name in required else "done"
    return info


def execute(ws, entry, log=print):
    stage = BY_NAME[entry["stage"]]
    stage_dir = ws.stage_dir(stage.name)
    run_dir = stage_dir / "runs" / entry["run_id"]
    if run_dir.exists():
        aside = run_dir.with_name("%s.superseded-%s" % (entry["run_id"], time.strftime("%Y%m%d-%H%M%S")))
        run_dir.rename(aside)
        log("  previous attempt kept at %s" % aside.relative_to(ws.dir))
    run_dir.mkdir(parents=True)
    record = {"format": "character-forge/run@1", "stage": stage.name, "run": entry["run_id"], "input_hash": entry["input_hash"],
              "mode": entry["mode"], "status": "running", "started": now(),
              "inputs": {k: _file_record(v, ws.dir) if v.is_file() else {"path": str(v)} for k, v in entry["inputs"].items()},
              "params_sha256": sha256_json(entry["params"]), "outputs": {}}
    write_json(run_dir / "run.json", record)
    write_json(stage_dir / "current.json", {"run": entry["run_id"]})
    ctx = Context(ws=ws, character=ws.load(), preset=ws.preset, machine=ws.machine, stage=stage.name, run_dir=run_dir,
                  mode=entry["mode"], inputs=entry["inputs"], upstream=entry["upstream"], params=entry["params"], log=log)
    started = time.monotonic()
    try:
        outputs = stage.run(ctx)
        gate = stage.gate(ctx, outputs)
        gate.write(run_dir)
        record["outputs"] = {k: _file_record(Path(v), ws.dir) for k, v in outputs.items()}
        record.update(status="done", gate=gate.status)
    except Planned:
        record.update(status="planned", plan=ctx.plan)
    except ForgeError as error:
        record.update(status="failed", error=str(error))
    except Exception as error:  # keep the traceback with the run for diagnosis
        record.update(status="failed", error="%s: %s" % (type(error).__name__, error))
        (run_dir / "traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
    record.update(finished=now(), seconds=round(time.monotonic() - started, 2))
    write_json(run_dir / "run.json", record)
    return record


def run(ws, only=None, until=None, mode=None, force=False, log=print):
    if only and only not in BY_NAME or until and until not in BY_NAME:
        raise ForgeError("Unknown stage; choose from: " + ", ".join(ORDER))
    names = [only] if only else (ORDER[:ORDER.index(until) + 1] if until else ORDER)
    for name in names:
        entry = evaluate(ws, mode)[name]
        state = entry["state"]
        if state == "blocked":
            log("%-14s blocked: %s" % (name, entry["reason"]))
            return EXIT_WAITING
        if state in SATISFIED and not (force and only):
            log("%-14s up-to-date (%s, run %s)" % (name, state, entry["run_id"]))
            continue
        if state == "awaiting-approval" and not (force and only):
            log("%-14s awaiting approval -> forge show %s --stage %s ; forge approve %s --stage %s --by human --note \"...\"" % (
                name, ws.id, name, ws.id, name))
            return EXIT_WAITING
        if state == "rejected" and not force:
            log("%-14s rejected: %s (change inputs, or rerun with --force)" % (name, entry.get("reason")))
            return EXIT_WAITING
        if state == "gate-failed" and not force:
            log("%-14s gate FAILED: %s\n               fix the cause (inputs/params/source), then rerun; see forge show %s --stage %s" % (
                name, entry.get("reason"), ws.id, name))
            return EXIT_FAILED
        log("%-14s running (%s mode, run %s)..." % (name, entry["mode"], entry["run_id"]))
        record = execute(ws, entry, log)
        if record["status"] == "planned":
            for step in record.get("plan", []):
                log("               would run: " + " ".join(step["command"]))
            log("%-14s dry-run: planned only; later stages need real or fake outputs." % name)
            return EXIT_WAITING
        if record["status"] != "done":
            log("%-14s FAILED: %s" % (name, record.get("error")))
            return EXIT_FAILED
        after = evaluate(ws, mode)[name]
        log("%-14s %s in %.1fs (gate %s)" % (name, after["state"], record["seconds"], record.get("gate")))
        if after["state"] == "gate-failed":
            log("               failing checks: %s" % after.get("reason"))
            return EXIT_FAILED
        if after["state"] == "awaiting-approval":
            log("               review: forge show %s --stage %s ; then forge approve %s --stage %s --by human|agent --note \"...\"" % (
                ws.id, name, ws.id, name))
            return EXIT_WAITING
    return EXIT_OK


def regate(ws, stage_name, mode=None):
    """Recompute a completed stage's gate from its existing outputs (e.g. after the roster changed)."""
    entry = evaluate(ws, mode)[stage_name]
    record = entry.get("run")
    if not record or record.get("status") != "done" or entry["state"] in ("stale", "blocked", "modified"):
        return None
    stage = BY_NAME[stage_name]
    run_dir = ws.stage_dir(stage_name) / "runs" / record["run"]
    ctx = Context(ws=ws, character=ws.load(), preset=ws.preset, machine=ws.machine, stage=stage_name, run_dir=run_dir,
                  mode=record["mode"], inputs=entry["inputs"], upstream=entry["upstream"], params=entry["params"])
    outputs = {k: _resolve(ws, v["path"]) for k, v in record["outputs"].items()}
    gate = stage.gate(ctx, outputs)
    gate.write(run_dir)
    return gate.to_json()


def clean(ws, log=print):
    """Remove superseded/failed attempts and non-current runs; keep every current run."""
    removed = 0
    for stage in ORDER:
        runs = ws.stage_dir(stage) / "runs"
        if not runs.is_dir():
            continue
        current = (current_run(ws, stage) or {}).get("run")
        for child in runs.iterdir():
            if child.is_dir() and child.name != current:
                shutil.rmtree(child)
                removed += 1
                log("removed %s/%s" % (stage, child.name))
    return removed
