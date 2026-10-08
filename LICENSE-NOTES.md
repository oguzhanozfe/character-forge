# Licence notes: third-party tools and models

**character-forge contains no third-party models, weights, generators, store assets or motion libraries.** It only
calls tools that *you* install and configure (`forge setup`). Each tool, checkpoint, auxiliary model, input image and
output has its own terms. MIT/Apache on a code repository does **not** clear a checkpoint, a base model or the
outputs. The notes below summarise terms as researched on 2026-10-09 (labelled SEARCHED in the source research); they
are not legal advice and may have changed. Verify before installing, and again before shipping anything.

| Tool | What forge uses it for | Terms to check (as researched) | Shipping risk |
| --- | --- | --- | --- |
| **Blender** (4.2+) | headless preflight, low mesh/UV/bake, rig/skin, renders, FBX export | GPL application; your own authored outputs are yours | Low. Input components must be separately cleared. |
| **Pixal3D** (via trellis.cpp) | reconstruction backend `pixal3d` | MIT code/parameters per upstream NOTICE; dependencies (DINOv3 helpers, background removal) have separate terms. **DINOv3 uses a custom licence, not MIT.** | Check the exact checkpoint/encoder files you downloaded. |
| **TRELLIS.2** (via trellis.cpp) | reconstruction backend `trellis2` | MIT model/code; auxiliary models/renderers separate | Check auxiliary models. |
| **trellis.cpp** | native Windows CLI for both | MIT port; model/encoder/remesher terms separate | As above. |
| **Hunyuan3D 2.0 / 2.1** | reconstruction backend `hunyuan3d` (shape + paint) | **Tencent Hunyuan Community licence. Territory restrictions extend to outputs: use/distribution in the EU, UK and South Korea is excluded.** Extra licence above 1M monthly active users. Not MIT. | **High for worldwide releases.** forge refuses this backend until `params.licence_ack` contains `"hunyuan3d"`, and the reconstruct gate warns on every run. A local run from another country does not authorise worldwide output distribution. |
| **HY-Motion 1.0** (not integrated) | - | Same territory exclusion (EU/UK/South Korea) for model and outputs | Do not add as a default. |
| **Kimodo** | text-to-motion for missing clips | Apache-2.0 code; SOMA/G1 checkpoints under the NVIDIA Open Model licence; **Kimodo-SMPLX-RP is internal R&D only (noncommercial)** | Use `Kimodo-SOMA-RP-v1.1` (default) and record the checkpoint hash; never ship SMPLX-RP output. |
| **SMPL / SMPL-X body models** (not integrated) | - | Research/noncommercial unless separately licensed | Do not route production through SMPL-X fitters without a commercial grant. |
| **LHM, GaussianAvatars and similar** (not integrated) | - | Noncommercial (CC-BY-NC / CC-BY-NC-SA) weights | Excluded. |
| **SkinTokens, Puppeteer, UniRig** (possible future skin-only adapters) | - | MIT / Apache code and weights per their model cards | Verify the exact checkpoint before adoption. |
| **Quad Remesher** (not integrated) | - | Proprietary; ordinary licences exclude automated/SDK batch use | Never call it from forge's headless batches without vendor clearance. |
| **Unity** | import, Avatar, prefab, tests | Unity editor licence (yours) | Store packs (e.g. paid gore/animation packs) must not be committed or redistributed. |
| **Hosted generators** (Meshy, Tripo, Rodin, Kaedim; not integrated) | - | Paid tiers grant output rights per their terms; free tiers may license outputs CC-BY or make them public | Uploading imagery to a cloud service is a privacy/rights decision for the owner. |
| **Image generators** (Codex/GPT image, etc.) for references | the agent may create reference images | Output rights assigned to the user subject to the provider's terms; uniqueness not guaranteed | Record provenance with `--provenance`; original fictional characters only. |

## Rules forge enforces

* Nothing in `.gitignore`d intermediate formats (`.blend .glb .ply .npz .obj .bvh`, weights, renders, logs) can enter a
  package; `forge package` refuses them and anything named like a review render.
* Every package receipt records the reconstruction backend, its licence string, the reference provenance and each motion
  clip's licence field.
* No model weights are ever downloaded by forge; tests and fake mode need none.

## Your responsibilities

1. Read each tool's current licence before installing it and before shipping outputs to each territory you sell in.
2. Keep exact checkpoint file hashes (the reconstruct receipt stores the executable and backend configuration hash).
3. Use only original, cleared references: no real-person likeness, celebrity, brand or franchise content, and no donor
   assets uploaded to third-party services.
4. Treat `approved` gates as your own review record; forge never claims legal or appearance clearance.
