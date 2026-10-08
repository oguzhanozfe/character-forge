using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.Animations;
using UnityEngine.Playables;
using Object = UnityEngine.Object;

namespace CharacterForge.Editor
{
    [Serializable]
    public sealed class ForgeImportReport
    {
        public string format = "character-forge/unity-import-report@1";
        public string mode = "real";
        public string unity_version;
        public string character;
        public bool avatar_valid;
        public bool avatar_human;
        public int mapped_human_bones;
        public string[] missing_required_bones = Array.Empty<string>();
        public int hitboxes;
        public string[] hitbox_regions = Array.Empty<string>();
        public int gore_regions;
        public int gore_meshes;
        public int expected_hitboxes;
        public int expected_gore_regions;
        public int materials;
        public int motions;
        public int motions_playable;
        public string prefab;
        public string[] errors = Array.Empty<string>();
    }

    // Validation shared by the batch importer and the EditMode tests. Measures; never edits the character.
    public static class CharacterValidator
    {
        public static int MappedHumanBones(Animator animator)
        {
            if (!animator || !animator.avatar || !animator.avatar.isHuman) return 0;
            int count = 0;
            for (int b = 0; b < (int)HumanBodyBones.LastBone; b++)
                if (animator.GetBoneTransform((HumanBodyBones)b)) count++;
            return count;
        }

        public static List<string> MissingRequired(Animator animator, IEnumerable<string> required)
        {
            var missing = new List<string>();
            foreach (var name in required)
            {
                var bone = ForgeRig.ParseHuman(name);
                if (bone == null || !animator || !animator.avatar || !animator.avatar.isHuman || !animator.GetBoneTransform(bone.Value))
                    missing.Add(name);
            }
            return missing;
        }

        public static List<string> ValidateHitboxes(GameObject root, IEnumerable<string> expectedRegions)
        {
            var errors = new List<string>();
            var boxes = root.GetComponentsInChildren<ForgeHitbox>(true);
            var seen = new HashSet<string>();
            foreach (var box in boxes)
            {
                if (!seen.Add(box.region)) errors.Add("duplicate hitbox region " + box.region);
                var capsule = box.GetComponent<CapsuleCollider>();
                if (!capsule || !(capsule.radius > 0) || !(capsule.height > 0)) errors.Add("hitbox " + box.region + " has no usable capsule");
                if (!box.bone || !ForgeRig.IsDescendant(box.transform, box.bone)) errors.Add("hitbox " + box.region + " is not under its bone");
            }
            foreach (var region in expectedRegions)
                if (!seen.Contains(region)) errors.Add("missing hitbox region " + region);
            return errors;
        }

        public static List<string> ValidateGore(GameObject root, IEnumerable<string> expectedParts, bool requireMeshes)
        {
            var errors = new List<string>();
            var parts = root.GetComponentsInChildren<ForgeGoreRegion>(true);
            var names = new HashSet<string>(parts.Select(p => p.part));
            foreach (var part in expectedParts)
                if (!names.Contains(part)) errors.Add("missing gore region " + part);
            foreach (var p in parts)
            {
                if (!p.cutBone) errors.Add("gore region " + p.part + " has no cut bone");
                if (requireMeshes && (!p.gibMesh || p.gibMesh.vertexCount == 0)) errors.Add("gore region " + p.part + " has no gib mesh");
            }
            return errors;
        }

        // Samples each clip through a PlayableGraph in edit mode: bones must stay finite and something must move.
        public static List<string> ValidatePlayback(GameObject instance, ForgeMotionLibrary library, out int playable, int samples = 4)
        {
            var errors = new List<string>();
            playable = 0;
            var animator = instance.GetComponentInChildren<Animator>(true);
            if (!animator) { errors.Add("no Animator"); return errors; }
            if (!library) { errors.Add("no motion library"); return errors; }
            var transforms = ForgeRig.Walk(animator.transform).ToArray();
            var bind = transforms.Select(t => (t.localPosition, t.localRotation)).ToArray();
            var graph = PlayableGraph.Create("CharacterForgeValidate");
            graph.SetTimeUpdateMode(DirectorUpdateMode.Manual);
            try
            {
                var output = AnimationPlayableOutput.Create(graph, "out", animator);
                foreach (var entry in library.entries)
                {
                    if (entry == null || !entry.clip) { errors.Add("library entry without clip: " + entry?.id); continue; }
                    if (!(entry.clip.length > 0)) { errors.Add("empty clip " + entry.id); continue; }
                    var clipPlayable = AnimationClipPlayable.Create(graph, entry.clip);
                    output.SetSourcePlayable(clipPlayable);
                    bool finite = true;
                    float moved = 0;
                    for (int s = 0; s < samples; s++)
                    {
                        clipPlayable.SetTime(entry.clip.length * s / Mathf.Max(1, samples - 1));
                        graph.Evaluate();
                        for (int i = 0; i < transforms.Length; i++)
                        {
                            var p = transforms[i].localPosition;
                            var q = transforms[i].localRotation;
                            if (!float.IsFinite(p.x) || !float.IsFinite(p.y) || !float.IsFinite(p.z) || !float.IsFinite(q.w)) finite = false;
                            moved = Mathf.Max(moved, Quaternion.Angle(q, bind[i].localRotation));
                        }
                    }
                    clipPlayable.Destroy();
                    if (!finite) errors.Add("clip " + entry.id + " produced nonfinite bones");
                    else if (moved < 0.01f) errors.Add("clip " + entry.id + " does not move any bone");
                    else playable++;
                }
            }
            finally
            {
                graph.Destroy();
                for (int i = 0; i < transforms.Length; i++)
                {
                    transforms[i].localPosition = bind[i].localPosition;
                    transforms[i].localRotation = bind[i].localRotation;
                }
            }
            return errors;
        }

        public static ForgeImportReport Validate(GameObject prefab, ForgeManifest manifest, string prefabPath)
        {
            var report = new ForgeImportReport { unity_version = Application.unityVersion, character = manifest.id, prefab = prefabPath };
            var errors = new List<string>();
            var instance = Object.Instantiate(prefab);
            try
            {
                var animator = instance.GetComponentInChildren<Animator>(true);
                report.avatar_valid = animator && animator.avatar && animator.avatar.isValid;
                report.avatar_human = report.avatar_valid && animator.avatar.isHuman;
                report.mapped_human_bones = MappedHumanBones(animator);
                report.missing_required_bones = MissingRequired(animator, manifest.required_bones).ToArray();
                var boxes = instance.GetComponentsInChildren<ForgeHitbox>(true);
                report.hitboxes = boxes.Length;
                report.hitbox_regions = boxes.Select(b => b.region).OrderBy(r => r).ToArray();
                report.expected_hitboxes = manifest.hitboxes.Length;
                errors.AddRange(ValidateHitboxes(instance, manifest.hitboxes.Select(h => h.region)));
                var gore = instance.GetComponentsInChildren<ForgeGoreRegion>(true);
                report.gore_regions = gore.Length;
                report.gore_meshes = gore.Count(g => g.gibMesh) + gore.Count(g => g.stumpMesh);
                report.expected_gore_regions = manifest.gore.Length;
                errors.AddRange(ValidateGore(instance, manifest.gore.Select(g => g.part), requireMeshes: false));
                report.materials = instance.GetComponentsInChildren<Renderer>(true).SelectMany(r => r.sharedMaterials).Where(m => m).Distinct().Count();
                var library = instance.GetComponent<ForgeCharacter>()?.motionLibrary;
                report.motions = library ? library.entries.Length : 0;
                if (library && library.entries.Length > 0)
                {
                    errors.AddRange(ValidatePlayback(instance, library, out var ok));
                    report.motions_playable = ok;
                }
                if (!report.avatar_valid) errors.Add("Avatar invalid");
                if (report.missing_required_bones.Length > 0) errors.Add("unmapped required bones: " + string.Join(", ", report.missing_required_bones));
            }
            finally
            {
                Object.DestroyImmediate(instance);
            }
            report.errors = errors.ToArray();
            return report;
        }
    }
}
