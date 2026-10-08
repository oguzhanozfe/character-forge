# character-forge

A gated, resumable pipeline that turns **a text brief or a reference image into a packaged, game-ready humanoid
character**: reconstruction, static preflight, low mesh/UV/bake, rig and skin, stress-pose screen, Unity import,
**animations in context** (shared motion library + generated gap-fillers), and final-form packaging.

It is built to be driven by an AI coding agent (Codex, Claude) **or** by hand. The agent runs stages, reads the gate
reports, shows you what to look at and asks for your approval at each gate. Nothing proceeds past a gate that needs a
human until a human approves it (configurable), and nothing but final forms ever leaves a character's workspace.

Zombies are the first preset (`zombie`: 52 Humanoid bones incl. 30 finger bones, 20 regional hitboxes, 9 severable
gore regions); `humanoid` is a generic preset. The pipeline is generalized from a production zombie workflow; see
[docs/PIPELINE.md](docs/PIPELINE.md) for where each gate comes from.

```
 brief / reference image
          |
   [1 reference] ----(approve: identity, A-pose)----+
          |                                         |
   [2 reconstruct]  Pixal3D | TRELLIS.2 | Hunyuan3D  |   one GPU job at a time (forge lock gpu)
          |                                         |
   [3 preflight]  scale/facing, components/debris, completeness, landmarks, individuality vs roster
          |       ----(approve: static model, silhouette, face)
   [4 lowmesh]    triangle budget, UVs with face texel priority, baked BaseColor/Normal/MetallicSmoothness
          |
   [5 rig]        contract skeleton fitted to landmarks, bone-heat skin (<=4), digits, FBX round trip, hitboxes, gore
          |
   [6 pose-screen] 13 stress poses: finite, stretch ratios, cloth cross-influence, seams, renders
          |       ----(approve: deformation)
   [7 unity-import] own Humanoid Avatar, material, 20 hitboxes, 9 gore regions (gib + stump meshes), prefab
          |       ----(approve: engine look)
   [8 motion-screen] pick motions from the shared library for THIS character, generate only missing ones (Kimodo),
          |          retarget, screen every clip (floor, loop seam, stretch, attack reach), export FBX clips
          |       ----(approve: motion in context)
   [9 package]    final forms only: <id>.fbx, Textures/, Motions/<id>@<clip>.fbx, character.manifest.json, receipt.json
```

Every stage run is keyed by a hash of its inputs, parameters, adapter mode and tool code. Unchanged stages are reused;
any change makes the stage and everything after it stale. Approvals are bound to the exact run and gate report.

## Quick start (no GPU, no downloads: fake mode)

```bash
git clone https://github.com/oguzhanozfe/character-forge && cd character-forge
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # the whole suite runs without Blender/GPU

forge new demo --brief "Gaunt night-shift pump attendant zombie in a torn oilskin coat" --mode fake
forge run demo                           # stops at the first gate that needs approval
forge show demo --stage reference        # what was produced + what to look at
forge approve demo --stage reference --by human --note "placeholder accepted for a dry run"
forge run demo                           # ...repeat show/approve/run at each gate...
forge gate demo --render                 # JSON/CSV gate summary + compact contact sheet PNG
forge package demo                       # -> packages/demo/ (fake placeholders in fake mode)
forge status
```

Fake mode replaces each external tool with a deterministic stand-in (a synthetic five-digit humanoid instead of a
reconstruction, procedural motions instead of Kimodo, a manifest contract check instead of Unity). The gates
themselves are real computations in every mode.

## Real mode

```bash
forge setup                      # interactive: Blender, Unity, Kimodo, trellis-cli/models, Hunyuan server URL
forge doctor                     # what is configured
forge new z30 --brief "..." --reference ref/front.png --provenance "generated with <tool>, owned" --mode real
forge add-reference z30 ref/portrait.png --view portrait --provenance "..."
forge run z30
```

Mix modes per adapter, e.g. real Blender on a fake reconstruction (the repository's own smoke test):
`forge new probe --brief "..." --mode fake --adapter blender=real`. Adapters: `reconstruct`, `blender`, `kimodo`,
`unity`; modes: `fake`, `real`, `dry-run` (prints the exact commands, runs nothing).

Read [LICENSE-NOTES.md](LICENSE-NOTES.md) before installing or shipping anything: **Hunyuan3D outputs are
territory-restricted (EU/UK/South Korea excluded)** and some checkpoints are noncommercial.

## Using it with an AI agent

Open the repository in Codex or Claude Code and ask, for example:
*"Make a zombie: a stocky dock worker in a padded vest. Use review policy human."* or *"Here is a reference image,
build the character and stop at each gate for me."* The agent follows [AGENTS.md](AGENTS.md) and the skill in
[.agents/skills/character-forge/SKILL.md](.agents/skills/character-forge/SKILL.md):

1. `forge new` from your brief or reference; if there is no reference it reads `reference-request.json` and, if it has an
   image tool, generates one and adds it with provenance.
2. `forge run`, then at each stop `forge show` + the contact sheet/renders, and it summarises the gate for you.
3. It asks you to approve (or records its own audit with `--by agent`, which only unblocks when you created the
   character with `--review-policy agent`).
4. After the model is approved in Unity it moves to motions in context, then packages final forms only.

## By hand

The same commands work from a terminal; open the PNGs and JSON reports listed by `forge show` yourself, and use the
Unity package (`unity/com.characterforge.core`) to import the package and review it on a turntable.

## Repository layout

| Path | What |
| --- | --- |
| `character_forge/` | Python package and `forge` CLI (stdlib only) |
| `character_forge/stages/` | the nine stages; each has `run` + `gate` |
| `character_forge/meshkit/` | pure-Python geometry: OBJ, skeleton contract, LBS skinning, 13 stress poses, gates, rasterizer, motion retarget/screen |
| `character_forge/adapters/` | Blender, reconstruction backends, Kimodo, Unity - each with fake and dry-run modes |
| `character_forge/data/presets/` | `zombie`, `humanoid` presets (contracts, budgets, thresholds - all PROPOSALS) |
| `blender/` | headless Blender scripts with explicit inputs/outputs |
| `kimodo/` | Kimodo generation script (runs in Kimodo's own Python) |
| `unity/com.characterforge.core/` | Unity package: importer, Avatar, hitboxes, gore baker, motion library, turntable, EditMode tests |
| `unity/SampleProject/` | tiny Unity project referencing the package |
| `config/` | `machine.example.json`; `forge setup` writes `machine.json` (ignored) |
| `characters/` | per-character workspaces (only small text records are committable) |
| `packages/` | packaged final forms (ignored; copy into your game) |
| `tests/` | pytest suite (synthetic fixtures generated at test time) |
| `docs/` | [PIPELINE](docs/PIPELINE.md), [GATES](docs/GATES.md), [MOTION](docs/MOTION.md), [ADAPTERS](docs/ADAPTERS.md), [UNITY](docs/UNITY.md), [EXTENDING](docs/EXTENDING.md) |

## Status (v0.1)

* Works today: every stage in fake mode; real Blender preflight / lowmesh / rig (bone heat, T-pose bind, FBX round trip) /
  stress-pose renders / motion FBX export; all gates; packaging rules; locks; approvals; the Unity package compiles
  against Unity 6000.3 assemblies.
* Configured but not exercised by the test-suite: real reconstruction backends, real Kimodo, Unity batch import (they need
  your GPU/tools); Unity EditMode tests run inside Unity, not in CI.
* Thresholds are proposals to calibrate on your own accepted characters. Gates detect risk; they do not approve looks.

The repository is private; no open-source licence is granted unless the owner adds one.
