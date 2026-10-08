using System;
using System.Collections.Generic;
using UnityEngine;

namespace CharacterForge.Editor
{
    // Hierarchy helpers shared by the importer, the builders and the validator.
    public static class ForgeRig
    {
        // Contract tail for bones whose capsule should end at a specific child (mirrors character_forge.meshkit.skeleton).
        static readonly Dictionary<string, string> Tail = new Dictionary<string, string>
        {
            { "Hips", "Spine" }, { "Spine", "Chest" }, { "Chest", "UpperChest" }, { "UpperChest", "Neck" }, { "Neck", "Head" },
            { "LeftShoulder", "LeftUpperArm" }, { "LeftUpperArm", "LeftLowerArm" }, { "LeftLowerArm", "LeftHand" }, { "LeftHand", "LeftMiddleProximal" },
            { "RightShoulder", "RightUpperArm" }, { "RightUpperArm", "RightLowerArm" }, { "RightLowerArm", "RightHand" }, { "RightHand", "RightMiddleProximal" },
            { "LeftUpperLeg", "LeftLowerLeg" }, { "LeftLowerLeg", "LeftFoot" }, { "LeftFoot", "LeftToes" },
            { "RightUpperLeg", "RightLowerLeg" }, { "RightLowerLeg", "RightFoot" }, { "RightFoot", "RightToes" },
        };

        public static Transform FindDeep(Transform root, string name)
        {
            if (root.name == name) return root;
            foreach (Transform child in root)
            {
                var hit = FindDeep(child, name);
                if (hit) return hit;
            }
            return null;
        }

        public static IEnumerable<Transform> Walk(Transform root)
        {
            yield return root;
            foreach (Transform child in root)
                foreach (var t in Walk(child))
                    yield return t;
        }

        public static bool IsDescendant(Transform t, Transform ancestor)
        {
            for (var p = t; p; p = p.parent) if (p == ancestor) return true;
            return false;
        }

        // World-space segment for a bone: to its contract child when present, else continuing the parent direction.
        public static void Segment(Transform root, Transform bone, float fallbackLength, out Vector3 start, out Vector3 end)
        {
            start = bone.position;
            Transform tail = null;
            if (Tail.TryGetValue(bone.name, out var tailName)) tail = FindDeep(bone, tailName);
            if (tail)
            {
                end = tail.position;
                return;
            }
            Vector3 direction = bone.parent ? (bone.position - bone.parent.position) : Vector3.up;
            if (bone.name == "Head" || direction.sqrMagnitude < 1e-10) direction = Vector3.up;
            end = start + direction.normalized * Mathf.Max(0.02f, fallbackLength);
        }

        // Character forward from the shoulders: Cross(right, up). Works whichever way the FBX root faces.
        public static Vector3 Forward(Transform root)
        {
            var left = FindDeep(root, "LeftUpperArm");
            var right = FindDeep(root, "RightUpperArm");
            if (!left || !right) return root.forward;
            var forward = Vector3.Cross(right.position - left.position, Vector3.up);
            return forward.sqrMagnitude > 1e-8 ? forward.normalized : root.forward;
        }

        public static HumanBodyBones? ParseHuman(string name)
        {
            return Enum.TryParse(name, out HumanBodyBones bone) && bone != HumanBodyBones.LastBone ? bone : (HumanBodyBones?)null;
        }

        public static HumanDescription Describe(Transform root, ForgeManifest.HumanEntry[] mapping)
        {
            var human = new List<HumanBone>();
            foreach (var entry in mapping)
            {
                var bone = ParseHuman(entry.human);
                if (bone == null) continue;
                var hb = new HumanBone { humanName = HumanTrait.BoneName[(int)bone.Value], boneName = entry.bone };
                hb.limit.useDefaultValues = true;
                human.Add(hb);
            }
            var skeleton = new List<SkeletonBone>();
            foreach (var t in Walk(root))
                skeleton.Add(new SkeletonBone { name = t.name, position = t.localPosition, rotation = t.localRotation, scale = t.localScale });
            return new HumanDescription
            {
                human = human.ToArray(), skeleton = skeleton.ToArray(), upperArmTwist = 0.5f, lowerArmTwist = 0.5f,
                upperLegTwist = 0.5f, lowerLegTwist = 0.5f, armStretch = 0.05f, legStretch = 0.05f, feetSpacing = 0f,
                hasTranslationDoF = false
            };
        }
    }
}
