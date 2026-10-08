# Animations in context

Author motion once, then fit and validate it on each character; generate only what is missing. Never generate a new
complete library per character.

## Motion format (`character-forge/motion@1`, "fmotion")

Per contract bone, per frame: a **global rotation delta relative to the standard T-pose** (quaternion w,x,y,z, Z-up,
facing -Y) plus the Hips position track. This is what Kimodo's `standard_tpose` global rotations are once converted
from y-up, so generated clips need no per-character conversion. Retargeting onto a character:

1. Rebuild the character's own T-pose orientation per bone (arm chains straightened to +/-X; fingers and the twist
   helper follow; torso and legs as in rest).
2. Posed global orientation = clip delta x T-pose orientation; local pose = rest/parent algebra (Blender convention).
3. Hips track scaled by hip-height ratio; in-place by default (planar travel removed, speed kept as metadata).
4. Bone-capsule ground clamp lifts the Hips on frames where the body would sink below its rest floor level.

Python does this (`character_forge/meshkit/motion.py`); `blender/export_motions.py` only writes the keys into
`<id>@<clip>.fbx` (armature only, Unity's `@` naming) and reports Blender's evaluation for the agreement check.

## Libraries

A library is a folder with `library.json`:

```json
{"format": "character-forge/motion-library@1", "name": "studio-zombie-v3",
 "clips": [{"id": "Walk_Shamble_02", "kind": "Walk", "region": null, "file": "clips/Walk_Shamble_02.fmotion.json",
            "tags": ["shamble"], "licence": "own mocap 2026", "source": "studio capture"}]}
```

Configure libraries in `config/machine.json -> motion_libraries` (searched in order) and per character in
`characters/<id>/motions/library.json`. Tools:

```
forge library synth [--dir motion-library] [--hits]   # own-authored procedural starter set (smoke-test quality)
forge library add --dir motion-library --clip some.fmotion.json --licence "..." [--tag shamble]
forge library list
```

Bringing your own clips: convert them to fmotion (any source that can give global rotations relative to a T-pose -
Kimodo/SOMA output via `fmotion_from_global_rotations`, or a Blender script that samples a T-pose-bound armature).
Clips that already exist as Unity Humanoid FBX do not need conversion for Unity: put them in a `ForgeMotionLibrary`
asset and apply it (see [UNITY.md](UNITY.md)); convert them only if you want the numerical screen.

## Slots and steering

The preset's motion profile defines slots (`pilot`: Idle, Walk, Run, Attack, Death, Hit-Chest; `full`: 5 idle,
3 walk, 3 run, 10 attack, 3 death, 3 reactions for each of 20 regions). Per character (`character.json -> motions`):

```json
"motions": {
  "include": ["Walk_Shamble_02"],
  "exclude": ["Run_Sprint_01"],
  "generate": [{"id": "z31_LimpWalk_01", "kind": "Walk", "prompt": "A person limps forward dragging the left leg...",
                "seconds": 6, "seed": 4101}]
}
```

Missing slots become Kimodo requests using the preset prompts (`motion_prompts`, `{region}` substituted). Kimodo runs
offline under the `gpu` lock with the text encoder on CPU; raw NPZ/BVH stay in the run folder (never packaged).

## Screening

Each selected clip is screened on this character: finite skin, floor penetration, grounded clips reaching the floor,
loop seams, stretch red flags, attack impact inside the clip and hand reach at impact (per unit height), and in real
mode the Python-vs-Blender agreement of the exported keys. Review flagged clips visually (Unity motion preview) before
approving; a numerical pass does not approve feel, contact timing or foot sliding.
