# Unity package: `com.characterforge.core`

Add it to any project (Unity 2022.3+; developed against 6000.3) via `Packages/manifest.json`:

```json
"com.characterforge.core": "file:<path-to-repo>/unity/com.characterforge.core"
```

or use the sample project in `unity/SampleProject`. The package contains no third-party or store assets.

## Import a packaged character

1. Copy `packages/<id>/` (real mode) into `Assets/Characters/<id>/`.
2. `Tools > Character Forge > Import Packaged Character...` -> pick its `character.manifest.json`.
   * model importer: Humanoid with the manifest's exact bone map and a skeleton description built from the model
     (its **own** Avatar, from the T-pose bind), no imported materials, readable mesh;
   * material: URP Lit if present, else Standard; BaseColor (sRGB), Normal (normal map), MetallicSmoothness (linear,
     smoothness in alpha);
   * motions: each `Motions/<id>@<clip>.fbx` imported as Humanoid copying the character Avatar, loop flags from the
     manifest; a `ForgeMotionLibrary` asset and an Animator controller (one state per clip, Idle default);
   * hitboxes: one capsule per region under its bone (`Hitbox_<Region>`, `ForgeHitbox`), Chest/Back split front/back;
   * gore: `Gore_<Part>` markers (`ForgeGoreRegion`) with baked gib and stump-cap meshes under `Gore/`;
   * prefab `<id>.prefab` with `ForgeCharacter` (id, preset, height, motion library).
3. `Tools > Character Forge > Turntable Preview (Selected Prefab)`, press Play: the character spins and cycles its motions.

The batch entry `CharacterForge.Editor.ForgeBatch.ImportCandidate` does the same headless and writes
`unity-report.json` for the `unity-import` gate.

## Plug in your own motion library

`Assets > Create > Character Forge > Motion Library`, fill `entries` (id, kind, region, Humanoid clip, loop, weight,
impact seconds, licence), select the library **and** a character prefab, then
`Tools > Character Forge > Apply Motion Library To Selected Prefab`. Any Humanoid clips work because every character
has its own Avatar; the state names in the generated controller are the entry ids. Game code can pick entries by
`kind`/`region` from `ForgeCharacter.motionLibrary`.

## EditMode tests

`Window > General > Test Runner > EditMode > Run All` (the sample project lists the package as `testable`), or
headless:

```
Unity -batchmode -projectPath unity/SampleProject -runTests -testPlatform EditMode -testResults results.xml
```

* `AvatarMappingTests`: a code-built contract skeleton yields a valid Humanoid Avatar with all 52 bones; a missing
  mapping is reported; unknown names are ignored.
* `MotionLibraryTests`: PlayableGraph playback moves bones and restores the bind pose; empty entries are reported; the
  controller has one state per entry with Idle as default.
* `HitboxAndGoreTests`: 20 regional hitboxes under their bones (Chest in front of Back), missing regions reported,
  9 gore regions present.
* `PackagedCharacterTests`: every imported real package passes Avatar/hitbox/gore/playback validation (ignored when
  none is imported).

These tests are not run in CI (no Unity licence on runners). The package is compile-checked locally against the Unity
6000.3 managed assemblies.
