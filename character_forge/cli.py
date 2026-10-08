"""`forge` command line. Exit codes: 0 ok, 1 stage/gate failed, 2 usage/config error, 3 waiting (approval/input)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, approvals, config, gates, library, lock, presets, runner
from .stages import ORDER
from .util import ForgeError, read_json
from .workspace import VIEWS, Workspace


def _ws(args):
    root = config.find_root(args.root)
    return Workspace(root, args.id)


def cmd_init_project(args):
    root = config.init_project(args.directory)
    print("character-forge project ready at %s (characters/, packages/, config/)" % root)
    return 0


def cmd_setup(args):
    root = config.find_root(args.root)
    data = config.setup(root, args.set, interactive=not args.non_interactive)
    print("wrote %s" % config.machine_path(root))
    for key in ("blender", "unity", "kimodo_python", "default_mode"):
        print("  %-14s %s" % (key, data.get(key) or "-"))
    return 0


def cmd_doctor(args):
    root = config.find_root(args.root)
    rows = config.doctor(root, config.load_machine(root))
    for r in rows:
        mark = "OK  " if r["ok"] else ("opt " if r["optional"] else "MISS")
        print("%s %-22s %s" % (mark, r["check"], r["detail"]))
    print("Fake mode needs nothing beyond Python. Real stages need the tools above (see LICENSE-NOTES.md before installing).")
    return 0 if all(r["ok"] or r["optional"] for r in rows) else 2


def cmd_presets(args):
    for name in presets.available():
        p = presets.load(name)
        print("%-10s %s" % (name, p.get("description", "")))
    return 0


def cmd_new(args):
    ws = _ws(args)
    adapters = {}
    for item in args.adapter or []:
        kind, _, mode = item.partition("=")
        if kind not in ("reconstruct", "blender", "kimodo", "unity") or mode not in ("fake", "real", "dry-run"):
            raise ForgeError("--adapter takes KIND=MODE with KIND in reconstruct|blender|kimodo|unity and MODE fake|real|dry-run")
        adapters[kind] = mode
    data = ws.create(args.brief, preset=args.preset, reference=args.reference, view=args.view, review_policy=args.review_policy,
                     mode=args.mode, motion_profile=args.motion_profile, height=args.height, seed=args.seed, provenance=args.provenance,
                     adapters=adapters)
    print("created %s (preset %s, mode %s, review policy %s)" % (ws.dir, data["preset"], data["mode"], data["review_policy"]))
    print("next: forge run %s" % ws.id)
    return 0


def cmd_add_reference(args):
    ws = _ws(args)
    target = ws.add_reference(args.image, args.view, args.provenance)
    print("added %s; the reference stage (and everything after it) will rerun" % target.relative_to(ws.dir))
    return 0


def cmd_run(args):
    ws = _ws(args)
    if args.stage and args.until:
        raise ForgeError("Use either --stage or --until")
    return runner.run(ws, only=args.stage, until=args.until, mode=args.mode, force=args.force)


def cmd_package(args):
    ws = _ws(args)
    code = runner.run(ws, until="package", mode=args.mode)
    if code == 0:
        print("package: %s" % ws.packages_dir())
    return code


def _status_rows(ws, mode=None):
    info = runner.evaluate(ws, mode)
    rows = []
    for name in ORDER:
        e = info[name]
        rows.append((name, e["state"], e.get("gate") or "-", e.get("approval") or ("-" if not e["needs_approval"] else "none"),
                     e.get("mode") or "-", (e.get("run") or {}).get("run", "-"), e.get("reason", "")))
    return rows


def cmd_status(args):
    root = config.find_root(args.root)
    ids = [args.id] if args.id else sorted(p.name for p in (root / "characters").iterdir() if (p / "character.json").is_file())
    if not ids:
        print("no characters yet: forge new <id> --brief \"...\"")
        return 0
    for identifier in ids:
        ws = Workspace(root, identifier)
        data = ws.load()
        print("%s  (preset %s, mode %s, review %s)" % (identifier, data["preset"], data["mode"], data["review_policy"]))
        for name, state, gate, approval, mode, run, reason in _status_rows(ws, args.mode):
            approval = approval if approval not in ("none",) or name in ws.preset.get("approvals", []) else "-"
            print("  %-14s %-18s gate %-5s approval %-9s %-8s %-12s %s" % (name, state, gate, approval, mode, run, reason[:90]))
    return 0


def cmd_gate(args):
    ws = _ws(args)
    stages = [args.stage] if args.stage else ORDER
    reports = []
    info = runner.evaluate(ws, args.mode)
    for name in stages:
        gate = runner.regate(ws, name, args.mode)
        reports.append((name, gate, runner.evaluate(ws, args.mode)[name]["state"] if gate else info[name]["state"]))
    out = gates.summarize(ws, reports)
    if args.render:
        from .contact import render_sheet
        sheet = render_sheet(ws, args.mode)
        print("contact sheet: %s" % sheet)
    if args.json:
        print(json.dumps(read_json(out / "summary.json"), indent=2))
    else:
        for name, gate, state in reports:
            if gate:
                print("%-14s %-5s pass %-3d warn %-3d fail %-3d (%s)" % (name, gate["status"], gate["counts"]["PASS"], gate["counts"]["WARN"],
                                                                    gate["counts"]["FAIL"], state))
            else:
                print("%-14s -     (%s)" % (name, state))
        print("reports: %s (summary.json/.csv, contact-sheet-request.json)" % out.relative_to(ws.root))
    return 0


def cmd_show(args):
    ws = _ws(args)
    entry = runner.evaluate(ws, args.mode)[args.stage]
    record = entry.get("run")
    print("%s / %s: %s %s" % (ws.id, args.stage, entry["state"], ("- " + entry["reason"]) if entry.get("reason") else ""))
    if not record:
        return 0
    run_dir = ws.stage_dir(args.stage) / "runs" / record["run"]
    print("run dir: %s" % run_dir)
    if (run_dir / "gate.json").is_file():
        gate = read_json(run_dir / "gate.json")
        print("gate %s  (pass %d, warn %d, fail %d)" % (gate["status"], gate["counts"]["PASS"], gate["counts"]["WARN"], gate["counts"]["FAIL"]))
        for c in gate["checks"]:
            if c["status"] in ("WARN", "FAIL") or args.all:
                print("  %-5s %-34s value=%s threshold=%s %s" % (c["status"], c["id"], json.dumps(c["value"])[:80], c["threshold"], c["message"]))
        print("review before approving:")
        for item in gate["human_review"]:
            print("  - " + item)
    print("outputs:")
    for label, out in record.get("outputs", {}).items():
        print("  %-24s %s" % (label, out["path"]))
    return 0


def cmd_approve(args, decision="approved"):
    ws = _ws(args)
    entry = approvals.record(ws, args.stage, decision, args.by, args.note, args.reviewer or "",
                             getattr(args, "waive_failures", False))
    policy = ws.load().get("review_policy", "human")
    effect = "unblocks the stage" if (args.by == "human" or policy == "agent" or decision == "rejected") else \
        "advisory only (review_policy=human): a human approval is still required"
    print("%s %s by %s for run %s: %s" % (args.stage, decision, args.by, entry["run"], effect))
    return 0


def cmd_reject(args):
    return cmd_approve(args, "rejected")


def cmd_lock(args):
    root = config.find_root(args.root)
    directory = config.lock_root(root, config.load_machine(root))
    if args.action == "status":
        rows = lock.status(directory)
        print("lock root: %s" % directory)
        for r in rows:
            print("  %-14s owner=%s host=%s pid=%s held=%ss heartbeat_age=%ss" % (r["name"], r["owner"], r["host"], r["pid"],
                                                                               r["held_seconds"], r["heartbeat_age_seconds"]))
        if not rows:
            print("  no locks held")
        return 0
    if not args.name or not args.owner:
        raise ForgeError("lock %s needs a name and --owner" % args.action)
    # Shell callers hold a lock across commands: record the parent shell's pid so liveness checks track the shell.
    import os
    named = lock.NamedLock(directory, args.name, args.owner, pid=os.getppid(), stale_seconds=args.stale)
    if args.action == "acquire":
        try:
            print(named.acquire(timeout=args.timeout, poll=min(10.0, max(0.5, args.timeout / 10)), log=print))
        except lock.LockTimeout as error:
            print(str(error), file=sys.stderr)
            return 3
    elif args.action == "heartbeat":
        named.heartbeat()
    elif args.action == "release":
        named.release()
    return 0


def cmd_library(args):
    root = config.find_root(args.root)
    machine = config.load_machine(root)
    if args.action == "synth":
        target = config.resolve_path(root, args.directory or machine.get("motion_libraries", ["motion-library"])[0])
        regions = list(presets.load(args.preset).get("hit_regions", {})) if args.hits else []
        print("wrote %s" % library.synth(target, regions))
        return 0
    if args.action == "add":
        if not args.directory or not args.clip or not args.licence:
            raise ForgeError("library add needs --dir, --clip and --licence")
        print("added %s" % library.add_clip(config.resolve_path(root, args.directory), Path(args.clip), args.licence, args.tag or []))
        return 0
    for value in machine.get("motion_libraries", []):
        lib = library.load(config.resolve_path(root, value))
        if not lib:
            print("%s: (no library.json)" % value)
            continue
        print("%s: %d clips" % (lib["name"], len(lib["clips"])))
        for clip in lib["clips"]:
            print("  %-28s %-8s %-14s %s" % (clip["id"], clip["kind"], clip.get("region") or "", clip.get("licence", "")))
    return 0


def cmd_clean(args):
    ws = _ws(args)
    removed = runner.clean(ws)
    print("removed %d superseded/non-current run folder(s); current runs kept" % removed)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="forge", description="character-forge: reference/brief -> gated, packaged game character")
    parser.add_argument("--root", help="project root (default: search upward for forge-project.json, or FORGE_ROOT)")
    parser.add_argument("--version", action="version", version="character-forge " + __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-project", help="create a project folder elsewhere (the repo itself is already one)")
    p.add_argument("directory")
    p.set_defaults(func=cmd_init_project)

    p = sub.add_parser("setup", help="write config/machine.json (tool paths); interactive by default")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="e.g. blender=C:/AI/Blender/.../blender.exe")
    p.add_argument("--non-interactive", action="store_true")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("doctor", help="check configured tools")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("presets", help="list character presets")
    p.set_defaults(func=cmd_presets)

    p = sub.add_parser("new", help="create a character workspace from a brief (and optional reference)")
    p.add_argument("id")
    p.add_argument("--brief", required=True)
    p.add_argument("--reference")
    p.add_argument("--view", default="front", choices=VIEWS)
    p.add_argument("--provenance", default="", help="where the reference came from and its rights")
    p.add_argument("--preset", default="zombie")
    p.add_argument("--review-policy", default="human", choices=("human", "agent"),
                   help="human: only human approvals unblock gates; agent: an AI reviewer's approval also unblocks")
    p.add_argument("--mode", choices=("fake", "real", "dry-run"), help="default mode for every adapter")
    p.add_argument("--adapter", action="append", metavar="KIND=MODE", help="per-adapter mode, e.g. blender=real reconstruct=fake")
    p.add_argument("--motion-profile")
    p.add_argument("--height", type=float)
    p.add_argument("--seed", type=int)
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("add-reference", help="add a reference image to a character")
    p.add_argument("id")
    p.add_argument("image")
    p.add_argument("--view", default="front", choices=VIEWS)
    p.add_argument("--provenance", default="")
    p.set_defaults(func=cmd_add_reference)

    p = sub.add_parser("run", help="run stages (resumable; reuses unchanged runs; stops at gates needing approval)")
    p.add_argument("id")
    p.add_argument("--stage", choices=ORDER, help="run only this stage")
    p.add_argument("--until", choices=ORDER, help="run up to and including this stage")
    p.add_argument("--mode", choices=("fake", "real", "dry-run"), help="override every adapter's mode for this invocation")
    p.add_argument("--force", action="store_true", help="rerun a failed/rejected gate, or with --stage rerun a finished stage")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("status", help="stage states for one or all characters")
    p.add_argument("id", nargs="?")
    p.add_argument("--mode", choices=("fake", "real", "dry-run"))
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("gate", help="recompute gate reports (JSON/CSV) and the contact-sheet request")
    p.add_argument("id")
    p.add_argument("--stage", choices=ORDER)
    p.add_argument("--render", action="store_true", help="render the compact contact sheet")
    p.add_argument("--json", action="store_true")
    p.add_argument("--mode", choices=("fake", "real", "dry-run"))
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("show", help="what a stage produced and what to review before approving")
    p.add_argument("id")
    p.add_argument("--stage", required=True, choices=ORDER)
    p.add_argument("--all", action="store_true", help="also list passing checks")
    p.add_argument("--mode", choices=("fake", "real", "dry-run"))
    p.set_defaults(func=cmd_show)

    for name, func in (("approve", cmd_approve), ("reject", cmd_reject)):
        p = sub.add_parser(name, help="%s the current run of a stage (bound to its input hash and gate report)" % name)
        p.add_argument("id")
        p.add_argument("--stage", required=True, choices=ORDER)
        p.add_argument("--by", required=True, choices=("human", "agent"))
        p.add_argument("--note", required=True, help="what was inspected and what remains open")
        p.add_argument("--reviewer", help="name of the person or agent")
        if name == "approve":
            p.add_argument("--waive-failures", action="store_true", help="human only: approve despite FAIL checks")
        p.set_defaults(func=func)

    p = sub.add_parser("package", help="run every stage through packaging (final forms only)")
    p.add_argument("id")
    p.add_argument("--mode", choices=("fake", "real", "dry-run"))
    p.set_defaults(func=cmd_package)

    p = sub.add_parser("lock", help="machine-wide named locks (single-GPU queue)")
    p.add_argument("action", choices=("acquire", "release", "heartbeat", "status"))
    p.add_argument("name", nargs="?", help="e.g. gpu, unity-batch")
    p.add_argument("--owner")
    p.add_argument("--timeout", type=float, default=7200)
    p.add_argument("--stale", type=float, default=3 * 3600)
    p.set_defaults(func=cmd_lock)

    p = sub.add_parser("library", help="shared motion libraries")
    p.add_argument("action", choices=("list", "synth", "add"))
    p.add_argument("--dir", dest="directory")
    p.add_argument("--clip")
    p.add_argument("--licence")
    p.add_argument("--tag", action="append")
    p.add_argument("--hits", action="store_true", help="synth: also one hit reaction per preset region")
    p.add_argument("--preset", default="zombie")
    p.set_defaults(func=cmd_library)

    p = sub.add_parser("clean", help="delete superseded and non-current runs of a character (keeps current runs)")
    p.add_argument("id")
    p.set_defaults(func=cmd_clean)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ForgeError as error:
        print("error: %s" % error, file=sys.stderr)
        return runner.EXIT_USAGE
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except BrokenPipeError:  # e.g. `forge status | head`
        return 0


if __name__ == "__main__":
    sys.exit(main())
