# Extending: new stages, adapters and gates

Planned extensions (parameterized headless Blender prep, region-restricted weights with an optional SkinTokens
adapter, earlier gates, material-library texturing) are meant to plug into the interfaces below.

## A new stage

1. Subclass `character_forge.stages.base.Stage` in `character_forge/stages/<name>.py`:
   * `name`, `title`, `version` (bump to invalidate old runs), `needs` (upstream stage names),
   * `adapter` (`reconstruct|blender|kimodo|unity|python`) - selects which mode applies,
   * `tool_files` - repo-relative scripts whose bytes join the run hash,
   * `params(ws, character, preset, machine)` - everything that should invalidate the run when changed,
   * `extra_inputs(...)` - files outside upstream stages (libraries, references),
   * `run(ctx)` -> `{label: Path}` outputs (write only under `ctx.run_dir`; use `ctx.mode`, `ctx.plan` for dry-run),
   * `gate(ctx, outputs)` -> `Gate` with `check(...)`, `info(...)`, `need_review(...)`, `view(...)`.
2. Insert it into `STAGES` in `character_forge/stages/__init__.py` (order = DAG order) and, if it needs approval, add
   its name to the preset's `approvals`. Downstream stages read its outputs as `ctx.inputs["<stage>.<label>"]`.

Example placements for v2: a `texture` stage between `lowmesh` and `rig` (material masks + library microdetail + bounded
repaint); an early `components` gate inside `preflight`.

## A new adapter / backend

* Reconstruction: add an entry under `reconstruct.backends` in `config/machine.json` (command template, `gpu`,
  `licence`, `requires_licence_ack`) - no code needed.
* Skin weights (e.g. SkinTokens `--use_skeleton --use_transfer`, Puppeteer skin-only): implement an adapter module with
  `fake(...)` / `real(...)` like `adapters/kimodo.py`, called from `RigStage.run` behind a `params.skin_backend`
  switch; keep the contract skeleton and fitted hand weights, then normalize/limit to 4 and let the existing rig and
  pose-screen gates judge the result (stretch, cross-influence, digits, round trip).
* Blender work: add a script under `blender/` taking explicit `--input/--output-dir` arguments, writing its own OBJ via
  `_forge_common.write_obj` when downstream needs vertex-indexed data, and list it in the stage's `tool_files`.

## A new gate check

Add measurements to `character_forge/meshkit/` (pure Python, testable without Blender), call them from a stage's
`gate`, put thresholds in the preset `thresholds` (PROPOSAL values), and add a pytest using generated fixtures
(`meshkit/synth.py` can produce deliberate defects).
