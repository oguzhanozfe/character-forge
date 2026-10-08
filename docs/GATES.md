# Gates

Every threshold is a **PROPOSAL** (preset `thresholds`), calibrated on earlier accepted characters and known failures.
A gate detects risk; it cannot certify a frightening, unique face. `FAIL` blocks; `WARN` means a reviewer must look.

## reference
* front reference present (FAIL), image unchanged since added, long side >= 1024 px (WARN), provenance recorded (WARN).
* Review: original fictional adult, A-pose with hands away from thighs, consistent clothing across views.

## reconstruct
* output written and is binary glTF; licence warning for territory-restricted backends (Hunyuan3D) (WARN).

## preflight (source geometry / components / individuality)
* finite coordinates (FAIL), degenerate triangles (WARN), non-manifold edges (WARN), height within 2 % (FAIL).
* **Component scan** on position-welded topology (UV seams do not split components): each component gets a body region
  from the nearest landmark segment; small components outside head/hands/feet are `debris_candidate` (WARN, never
  deleted automatically); small components inside them are `review` (could be teeth, fingertips, buttons, gore).
* **Completeness**: geometry near head top, both wrists and fingertips, both feet and toes (FAIL if missing).
* **Individuality**: front/side/three-quarter silhouettes at equal height compared (IoU) with every other character's
  current preflight and any `roster_dirs` (`*.silhouettes.json`). Mean IoU >= 0.975 FAIL (near duplicate), >= 0.93 WARN.
  Geometry differences must survive loss of colour; height alone never passes.
* Landmarks: from the backend (fake), a heuristic estimate (real; review!) or `landmarks_override`.

## lowmesh (UV and bake)
* triangle budget (FAIL), material count (WARN), faces without UVs (FAIL), nonfinite UVs (FAIL), UVs outside 0..1 (WARN).
* **Face texel density**: head triangles smaller than one texel (WARN > 0, FAIL > 500 - the production head repair went
  from 16,991 to 13), head/body density ratio >= 1.2 (WARN), microscopic UV islands (WARN).

## rig (contract and round trip)
* all preset bones present (FAIL), 30 finger bones (FAIL), skin matches the mesh, no unweighted vertices, finite
  weights, <= 4 influences, normalized within 1e-4, weights only on deform bones (all FAIL).
* **FBX round trip**: export the T-pose bind, re-import into an empty scene, compare world bone heads and bind vertices
  (<= 0.1 mm, FAIL) and bone names. A valid Avatar does not establish good weights.
* **Hand digit chains**: distal finger cross-sections per hand counted on the welded mesh (expect 4 + thumb); fewer is
  WARN (FAIL at <= 1). Finger bones alone do not prove mesh fingers.
* hit regions and gore parts have dominated geometry (FAIL if empty).

## pose-screen (13 stress poses)
`rest, elbow45, elbow90, elbow135, claw, fist, twist, wrist, reach, raise, crouch, crossbody, headturn` on the final rig.
* finite skinned vertices (FAIL).
* **Stretch**: per pose, edges stretched beyond 3x rest length (WARN if any; FAIL above 100 edges or 8x). The production
  coat failure measured 1,046 edges > 3x, worst 21x, while weights were finite and the FBX round trip passed.
* **Cross-influence**: vertices with >= 25 % arm-chain weight lying beyond 2x the arm's flesh radius (coat pockets/thigh
  cloth following the arms), WARN above 0.5 % of vertices.
* **Seams**: open boundaries of different components near wrists/neck - growth of their gap through the poses (WARN > 1 cm).
* Real mode: Python-vs-Blender agreement of posed bone heads (FAIL >= 1 mm) and Cycles CPU renders of the 8 review poses.

## unity-import
Avatar valid and Humanoid, every required bone mapped, hitbox count = preset regions (20), gore regions = 9, no import
errors. Fake mode: contract checked from the manifest (WARN that no import happened).

## motion-screen
All motion slots filled (FAIL). Per clip (sampled frames + impact frame): finite (FAIL), floor penetration > 3 cm,
grounded clip never reaches the floor (> 6 cm), loop seam > 2 cm, stretch red flags, attack impact inside the clip
(all WARN). Licence/provenance recorded for each clip (WARN). Real mode: exported FBX keys reproduce the screened pose
(FAIL >= 1 mm). Procedural stand-ins in fake mode are WARN.

## package
Only `<id>.fbx`, `Textures/*.png|tga|jpg|exr`, `Motions/<id>@<clip>.fbx`, `character.manifest.json`, `receipt.json`,
`README.txt`; intermediate extensions and review-render names are refused; size budget from the preset.
