# Adapters

| Adapter | Real mode | Fake mode | Dry-run |
| --- | --- | --- | --- |
| `reconstruct` | configured backend command (`config/machine.json -> reconstruct.backends`), under the `gpu` lock | synthetic A-pose humanoid (seeded by the character) + exact landmarks | prints the command |
| `blender` | `blender --background --factory-startup --python-exit-code 1 --threads N --python blender/<script>.py -- ...` | pure-Python equivalents (normalize, copy, synthetic weights, JSON round trip) | prints the command |
| `kimodo` | `kimodo_python kimodo/generate_motions.py ...` under the `gpu` lock, offline env | procedural clips | prints the command |
| `unity` | `Unity -batchmode -quit -projectPath ... -executeMethod CharacterForge.Editor.ForgeBatch.ImportCandidate` under the `unity-batch` lock | manifest contract check | prints the command |

Choose per character: `forge new <id> --mode real --adapter unity=fake` or edit `character.json -> adapters`.
`forge run --mode X` overrides all adapters for one invocation (and therefore changes run hashes).

## Reconstruction backends

Command templates use `{reference}`, `{output_glb}`, `{seed}`, `{python}`, `{out_dir}` and the backend's `vars`.
The shipped templates target the trellis.cpp native CLI (`--model pixal3d` / `--model trellis`) and a local
Hunyuan3D API server (`character_forge.adapters.hunyuan_client`, POST `/generate`; verify the request fields
against your server version). Add your own backend by adding an entry with a `command` list; set `"gpu": true` to run
it under the GPU lock and `"requires_licence_ack": true` with a `licence` text for restricted models.

Pin what matters for reproducibility: the executable is hashed into the receipt; record checkpoint file hashes in the
backend's `vars` or description. The folder name of an install does not identify the loaded flow.

## Blender scripts

| Script | Inputs | Outputs |
| --- | --- | --- |
| `preflight.py` | `--source glb/obj/fbx --height --up --rotate-z` | `static.blend`, `static.obj`, `Textures/source_*.png`, `preflight-blender.json` |
| `lowmesh.py` | `--source static.blend --id --triangles --texture-size [--no-bake --reunwrap --head-priority]` | `low.blend`, `low.obj`, `Textures/<id>_*.png`, `lowmesh-blender.json` |
| `rig_skin.py` | `--mesh low.blend --skeleton skeleton.json --id --max-influences` | `rig.blend`, `bind.fbx`, `skin.json`, `rigged.obj`, `skeleton-blender.json`, `roundtrip.json` |
| `pose_render.py` | `--rig rig.blend --poses stress-poses.json --height` | `renders/<pose>.png`, `renders/index.json` |
| `export_motions.py` | `--rig rig.blend --baked-dir --id` | `Motions/<id>@<clip>.fbx`, `export-index.json` |
| `contact_sheet.py` | `--rig rig.blend --request contact-sheet-request.json [--poses]` | one tiled PNG |

All renders are Cycles **CPU** with few samples so review never competes with GPU jobs. Scripts write OBJ themselves
(exact vertex order) because downstream skin data is indexed by vertex.

## Locks

`forge lock acquire gpu --owner me` / `release` / `heartbeat` / `status`. Lock folders are compatible with the original
`shared_lock.py` layout (`<root>/<name>.lock/owner.json`), so pointing `lock_root` at another tool's lock folder shares
one GPU queue. A lock is reclaimed only when its holder process is gone (same host) or its heartbeat is older than the
lease on another host; a stale heartbeat never steals a live process's lock; timeouts never stop anything.
