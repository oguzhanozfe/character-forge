---
name: character-forge
description: Build a game-ready humanoid character (zombies first) from a text brief or a reference image with the forge CLI - reconstruct, preflight, low mesh, rig, stress-pose screen, Unity import, animations in context, final-form packaging - stopping at every gate for human approval. Use when asked to create, repair, review, animate or package a character in this repository.
---

# character-forge skill

You run the pipeline; the human decides at the gates. Read `AGENTS.md` first (non-negotiables). All commands are run
from the repository root (`forge` is installed by `pip install -e .`; otherwise use `python -m character_forge`).

## 0. Orient

```
forge doctor            # which tools are configured; fake mode needs none
forge status            # existing characters and where each one stopped
forge presets
```
If a needed tool is missing, tell the human what `forge setup` needs; do not install anything yourself.
Decide the mode with the human: `fake` (dry rehearsal, no GPU), `real`, or a mix (`--adapter blender=real`).

## 1. Create the character

From a brief:
```
forge new <id> --brief "<occupation, build, age, clothing construction, damage, gait/attack personality>" \
  --preset zombie --review-policy human [--mode real]
```
From a reference (also add a portrait if you have one):
```
forge new <id> --brief "..." --reference <front.png> --provenance "<tool/author, rights>"
forge add-reference <id> <portrait.png> --view portrait --provenance "..."
```
Ids are lowercase (`z31-shift-fixer`). Check the brief against the preset's `reference_guidance` (original fictional
adult, A-pose with hands away from thighs, consistent clothing, separate portrait).

## 2. Reference gate

`forge run <id>` stops at `reference`. If there is no front image, read
`characters/<id>/stages/reference/runs/<run>/reference-request.json`: it contains ready prompts for the missing views.
If you have an image-generation tool and the human agrees, generate them, then `forge add-reference ... --provenance`.
Show the image(s) to the human and ask: identity right? pose right? Then approve with their words.

## 3. Model gates (reconstruct -> preflight -> lowmesh -> rig -> pose-screen)

* `reconstruct` runs the configured backend once (single GPU queue). Hunyuan3D is refused without a licence ack -
  explain LICENSE-NOTES.md instead of adding the ack yourself.
* `preflight` stops for approval. Open `preview.png`; read the WARN/FAIL checks: debris candidates (never delete;
  ask), missing anatomy (FAIL: hands/feet/head missing), individuality vs roster (nearest neighbours listed).
  If landmarks look wrong, write corrected positions to `landmarks_override` in `characters/<id>/character.json`
  (copy from `landmarks.json`) and rerun.
* After two failed anatomical candidates for the same defect (e.g. fused fingers), stop regenerating; propose reusing
  known-good fitted parts instead.
* `lowmesh` and `rig` usually continue automatically; FAIL means a hard contract break (budget, unweighted vertices,
  missing bones, FBX round trip drift) - fix the cause and rerun.
* `pose-screen` stops for approval. Open `pose-sheet.png` and (real mode) `renders/*.png`: elbows, fist/claw,
  wrist twist, crouch, cross-body, head turn. Report stretch red flags with the worst vertices and poses. A clean table
  does not approve appearance.

## 4. Engine gate (unity-import)

Real mode imports the candidate into the configured Unity project in batchmode and validates Avatar, 20 hitboxes,
9 gore regions. Ask the human to look at it in Unity: `Tools > Character Forge > Turntable Preview`. In fake mode,
say clearly that no engine import happened.

## 5. Animations in context (motion-screen)

1. The stage fills the preset's motion profile (`pilot`: 6 clips; `full`: 5 idle/3 walk/3 run/10 attack/3 death/3 hits
   per region) from the shared libraries in `config/machine.json -> motion_libraries`, then generates **only the
   missing slots** with Kimodo (real) or procedural stand-ins (fake).
2. Steer it with `characters/<id>/character.json -> motions`: `include` (clip ids to force), `exclude`, `generate`
   (`{"id","kind","region","prompt","seconds","seed"}` for character-specific moves, e.g. a limp).
3. Every selected clip is retargeted onto this rig and screened: floor penetration, never touching the floor, loop seam,
   stretch, attack reach at impact; plus a Python-vs-Blender agreement probe in real mode.
4. Show the human `motion-report.csv`, the flagged clips (and Unity motion preview), and ask for approval.
   Prefer reusing library clips over generating new ones; never generate a whole new library per character.

## 6. Package

`forge package <id>` writes `packages/<id>/` with final forms only and a receipt. Tell the human where it is and how
to import it (`Tools > Character Forge > Import Packaged Character...`). Do not commit packages or intermediates.

## 7. Finish

`forge gate <id> --render` for a final summary, `forge clean <id>` to drop superseded runs, then report: modes used
(fake/real per adapter), gate status per stage, WARN items still open, what the human approved (their words), licence
notes for the backend/motions used, and next steps.

## Reading gate reports

`characters/<id>/stages/<stage>/runs/<run>/gate.json` (+ `gate.csv`): `status` PASS/WARN/FAIL, `checks[]` with
`value`/`threshold`/`message`, `human_review[]` (what a person must still look at), `contact_sheet_views[]`.
`characters/<id>/gates/summary.json|csv` aggregates all stages; `contact-sheet-request.json` lists only the views worth
rendering. Thresholds are PROPOSALS from a previous production; mention when a value is borderline.
