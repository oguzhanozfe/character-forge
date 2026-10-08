# Pipeline

Origin: generalized from a production zombie workflow (fifty unique zombies for a first-person shooter) and its
2026-10 upgrade research: *upgrade the process first, keep installed reconstruction as the baseline, reject defects
before expensive downstream work, share hands/skeleton conventions/motions but preserve each character's own garment
construction, face and silhouette.* Timings and thresholds from that work are PROPOSALS here.

## Stages

| # | Stage | Adapter | Outputs (in `characters/<id>/stages/<stage>/runs/<hash>/`) | Approval (zombie preset) |
| --- | --- | --- | --- | --- |
| 1 | `reference` | reconstruct | `references.json`, `reference-request.json` (prompts for missing views) | yes |
| 2 | `reconstruct` | reconstruct | `source.glb` (real) / `source.obj` (fake), receipt with command, hashes, licence | - |
| 3 | `preflight` | blender | `static.blend`, `static.obj`, `landmarks.json`, `analysis.json`, `silhouettes.json`, `preview.png` | yes |
| 4 | `lowmesh` | blender | `low.blend`, `low.obj`, `Textures/<id>_{BaseColor,Normal,MetallicSmoothness}.png`, `analysis.json` | - |
| 5 | `rig` | blender | `skeleton.json`, `skin.json`, `rigged.obj`, `rig.blend` (A-pose rest), `bind.fbx` (T-pose bind), `roundtrip.json`, `hitboxes.json`, `gore.json` | - |
| 6 | `pose-screen` | blender | `pose-report.json/.csv`, `pose-sheet.png`, `renders/*.png` (real), `stress-poses.json` | yes |
| 7 | `unity-import` | unity | `candidate/` (model+textures+manifest), `unity-report.json` | yes |
| 8 | `motion-screen` | kimodo (+blender for FBX) | `motion-plan.json`, `motion-report.json/.csv`, `baked/*.baked.json`, `Motions/<id>@<clip>.fbx`, `blender-agreement.json` | yes |
| 9 | `package` | python | `packages/<id>/` + `receipt.json` | - |

Which stages need approval comes from the preset (`approvals`). With `--review-policy human` only `--by human`
approvals unblock; with `agent`, an agent's recorded self-audit also unblocks (rejections always block).

## Resume and staleness

A run's id is the first 12 hex digits of a SHA-256 over: stage name and version, adapter mode, stage parameters
(from the preset and `character.json`), the bytes of every input (upstream outputs, references, library clips) and the
bytes of the stage's own code and Blender/Kimodo scripts. `forge run` reuses a run whose hash matches and whose
outputs are intact (size/mtime, then SHA-256). Otherwise it creates a new run folder; previous attempts are moved
aside (`<hash>.superseded-<time>`), never overwritten. `forge clean <id>` deletes non-current runs.

States: `blocked`, `not-run`, `stale`, `failed`, `planned` (dry-run), `modified` (outputs edited after the run),
`gate-failed`, `awaiting-approval`, `rejected`, `approved`, `done`.

## Interchange conventions

Metres, Z up, the character faces -Y, its left is +X (Blender's convention). Bone names follow Unity's
`HumanBodyBones` (`Hips`, `LeftUpperArm`, `LeftIndexProximal`, ...) plus `LeftForearmTwist`/`RightForearmTwist`
helpers. Bone matrices are Blender `matrix_local` (Y along the bone; X is the hinge: +X flexes elbows, fingers and hips
forward, -X flexes knees). Python is the single source of truth for landmarks -> skeleton, the stress poses, retargeting
and every metric; Blender reproduces them (measured agreement on the smoke test: < 1 micrometre).

## What came from where

| Source practice | Here |
| --- | --- |
| `pipeline.py` stage records, hashed evidence, owner vs self-audit decisions | runner, run records, `approvals.json`, review policies |
| `shared_lock.py` (single GPU queue) | `forge lock` + automatic `gpu`/`unity-batch` locks; never steals a live lease |
| `inspect_character_mesh.py` (normalize, Y-up detection, neutral renders) | `blender/preflight.py` |
| `audit_fitted_character.py` (finite/<=4/normalized weights, bind drift, A->T edge stretch >3x) | rig + pose-screen gates |
| `rig_diagnostics.py` + `joint_stress.py` (13 controlled poses) | `meshkit/skinning.py` `STRESS_POSES` + `blender/pose_render.py` |
| `export_humanoid_bind.py` (T-pose bind) / `check_rig_roundtrip.py` | `blender/rig_skin.py` T-pose bind + FBX re-import comparison |
| `generate_*_motions.py` (Kimodo, offline, seeds, raw retention) | `kimodo/generate_motions.py` |
| `retarget_z01_motions.py` (SOMA T-pose global rotations -> rig) | `meshkit/motion.py` `retarget` + `blender/export_motions.py` |
| `ZombieGoreBaker.cs` (9 parts, >=50 % subtree triangles, gib + stump caps) | `unity/.../GoreBaker.cs` |
| `ModularZombieAssets.cs` (own Humanoid Avatar, 20 regional hitboxes) | `unity/.../CharacterImporter.cs`, `HitboxBuilder.cs` |
| Individuality re-audit (equal-height silhouettes vs neighbours) | preflight individuality gate |

Not ported (yet): foot-contact IK and loop polishing from the production retargeter (a cheaper bone-capsule ground
clamp is used), learned skin-only weights (SkinTokens/Puppeteer adapters), LOD generation, crowd/performance checks.
