"""Gate reports: structured checks with PASS/WARN/FAIL, written as JSON + CSV, plus contact-sheet requests.

A gate measures risk; it never certifies appearance. WARN means "a human or agent must look", FAIL blocks.
"""
from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path

from .util import now, sha256_file, write_json, write_text

ORDER = {"PASS": 0, "INFO": 0, "WARN": 1, "FAIL": 2}


class Gate:
    def __init__(self, stage, character_id, mode):
        self.stage = stage
        self.character_id = character_id
        self.mode = mode
        self.checks = []
        self.metrics = {}
        self.review = []      # things a human/agent must look at even when numbers pass
        self.views = []       # contact-sheet view requests

    def check(self, check_id, ok, value=None, threshold=None, message="", on_fail="FAIL"):
        status = "PASS" if ok else on_fail
        self.checks.append({"id": check_id, "status": status, "value": _plain(value), "threshold": _plain(threshold),
                            "message": message})
        return ok

    def info(self, check_id, value=None, message=""):
        self.checks.append({"id": check_id, "status": "INFO", "value": _plain(value), "threshold": None, "message": message})

    def need_review(self, text):
        self.review.append(text)

    def view(self, name, kind="static", pose=None, focus=None, reason=""):
        self.views.append({"name": name, "kind": kind, "pose": pose, "focus": focus, "reason": reason})

    @property
    def status(self):
        worst = max((ORDER[c["status"]] for c in self.checks), default=0)
        return {0: "PASS", 1: "WARN", 2: "FAIL"}[worst]

    def to_json(self):
        return {"format": "character-forge/gate@1", "character": self.character_id, "stage": self.stage, "mode": self.mode,
                "status": self.status,
                "counts": {s: sum(1 for c in self.checks if c["status"] == s) for s in ("PASS", "WARN", "FAIL", "INFO")},
                "checks": self.checks, "metrics": _plain(self.metrics), "human_review": self.review,
                "contact_sheet_views": self.views,
                "note": "Automated gates detect risk; visual/identity judgement and approval stay with the reviewer."}

    def write(self, directory: Path):
        directory = Path(directory)
        write_json(directory / "gate.json", self.to_json())
        write_text(directory / "gate.csv", checks_csv(self.checks, self.stage))
        return directory / "gate.json"


def checks_csv(checks, stage):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["stage", "check", "status", "value", "threshold", "message"])
    for c in checks:
        writer.writerow([stage, c["id"], c["status"], json.dumps(c["value"]) if isinstance(c["value"], (dict, list)) else c["value"],
                         c["threshold"], c["message"]])
    return buffer.getvalue()


def _plain(value):
    if isinstance(value, float):
        return round(value, 6) if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


def gate_hash(run_dir: Path):
    path = Path(run_dir) / "gate.json"
    return sha256_file(path) if path.is_file() else None


def summarize(ws, stage_reports):
    """stage_reports: [(stage, gate_json or None, state)] -> summary JSON/CSV and a contact-sheet request."""
    rows, views = [], []
    for stage, gate, state in stage_reports:
        if gate is None:
            rows.append({"stage": stage, "state": state, "status": None, "pass": 0, "warn": 0, "fail": 0})
            continue
        rows.append({"stage": stage, "state": state, "status": gate["status"], "pass": gate["counts"]["PASS"],
                     "warn": gate["counts"]["WARN"], "fail": gate["counts"]["FAIL"]})
        for v in gate.get("contact_sheet_views", []):
            views.append(dict(v, stage=stage))
    out = ws.dir / "gates"
    write_json(out / "summary.json", {"format": "character-forge/gate-summary@1", "character": ws.id, "created": now(), "stages": rows})
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["stage", "state", "status", "pass", "warn", "fail"])
    for r in rows:
        writer.writerow([r["stage"], r["state"], r["status"], r["pass"], r["warn"], r["fail"]])
    write_text(out / "summary.csv", buffer.getvalue())
    request = {"format": "character-forge/contact-sheet-request@1", "character": ws.id, "created": now(),
               "instructions": "Render ONLY these views (compact sheet). Neutral light, orthographic, equal height. "
                               "Real mode: `forge gate <id> --render` runs blender/contact_sheet.py. Never publish the sheet.",
               "views": views}
    write_json(out / "contact-sheet-request.json", request)
    return out
