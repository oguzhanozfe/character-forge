# Character Forge sample project

Minimal Unity project that references the local package `com.characterforge.core` (see `Packages/manifest.json`).
No third-party or store assets are included.

1. Open this folder with Unity 6000.3 (2022.3+ should also work; the package declares 2022.3).
2. Copy a **real-mode** package from `<repo>/packages/<id>/` to `Assets/Characters/<id>/`.
3. `Tools > Character Forge > Import Packaged Character...` and pick its `character.manifest.json`.
4. Select the generated prefab, then `Tools > Character Forge > Turntable Preview (Selected Prefab)` and press Play.
5. `Window > General > Test Runner > EditMode > Run All` runs the package tests (they also validate imported characters).

`forge run <id>` with `unity` in real mode copies the candidate to `Assets/CharacterForge/Candidates/<id>/` and runs the
import + validation in batchmode; those folders are git-ignored.
