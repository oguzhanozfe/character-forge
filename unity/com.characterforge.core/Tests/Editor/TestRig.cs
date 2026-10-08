using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace CharacterForge.Editor.Tests
{
    // Builds a contract-named T-pose hierarchy (52 Humanoid bones + twist helpers) in code: no assets needed.
    public static class TestRig
    {
        public static readonly string[] Fingers = { "Thumb", "Index", "Middle", "Ring", "Little" };
        public static readonly string[] Segments = { "Proximal", "Intermediate", "Distal" };

        public static GameObject Build(string name = "TestCharacter")
        {
            var root = new GameObject(name);
            Transform Add(string bone, Transform parent, Vector3 worldPosition)
            {
                var t = new GameObject(bone).transform;
                t.SetParent(parent, false);
                t.position = worldPosition;
                return t;
            }
            var hips = Add("Hips", root.transform, new Vector3(0, 0.95f, 0));
            var spine = Add("Spine", hips, new Vector3(0, 1.07f, 0));
            var chest = Add("Chest", spine, new Vector3(0, 1.19f, 0));
            var upper = Add("UpperChest", chest, new Vector3(0, 1.31f, 0));
            var neck = Add("Neck", upper, new Vector3(0, 1.47f, 0));
            Add("Head", neck, new Vector3(0, 1.55f, 0));
            foreach (var (side, sx) in new[] { ("Left", -1f), ("Right", 1f) })
            {
                var shoulder = Add(side + "Shoulder", upper, new Vector3(sx * 0.04f, 1.43f, 0));
                var arm = Add(side + "UpperArm", shoulder, new Vector3(sx * 0.18f, 1.43f, 0));
                var fore = Add(side + "LowerArm", arm, new Vector3(sx * 0.45f, 1.43f, 0));
                Add(side + "ForearmTwist", fore, new Vector3(sx * 0.57f, 1.43f, 0));
                var hand = Add(side + "Hand", fore, new Vector3(sx * 0.70f, 1.43f, 0));
                for (int f = 0; f < Fingers.Length; f++)
                {
                    var parent = hand;
                    float z = f == 0 ? 0.04f : 0.03f - f * 0.015f;
                    float x = f == 0 ? 0.72f : 0.79f;
                    for (int s = 0; s < 3; s++)
                        parent = Add(side + Fingers[f] + Segments[s], parent, new Vector3(sx * (x + s * 0.03f), 1.43f, z));
                }
                var leg = Add(side + "UpperLeg", hips, new Vector3(sx * 0.09f, 0.92f, 0));
                var shin = Add(side + "LowerLeg", leg, new Vector3(sx * 0.09f, 0.5f, 0));
                var foot = Add(side + "Foot", shin, new Vector3(sx * 0.09f, 0.08f, 0));
                Add(side + "Toes", foot, new Vector3(sx * 0.09f, 0.02f, 0.12f));
            }
            return root;
        }

        public static ForgeManifest.HumanEntry[] Mapping(GameObject root, params string[] skip)
        {
            return System.Enum.GetNames(typeof(HumanBodyBones))
                .Where(n => n != "LastBone" && !skip.Contains(n) && ForgeRig.FindDeep(root.transform, n))
                .Select(n => new ForgeManifest.HumanEntry { human = n, bone = n }).ToArray();
        }

        public static Animator WithAvatar(GameObject root, ForgeManifest.HumanEntry[] mapping)
        {
            var avatar = AvatarBuilder.BuildHumanAvatar(root, ForgeRig.Describe(root.transform, mapping));
            var animator = root.GetComponent<Animator>() ?? root.AddComponent<Animator>();
            animator.avatar = avatar;
            return animator;
        }

        public static readonly string[] ZombieRegions =
        {
            "Head", "Neck", "Chest", "Back", "Abdomen", "Pelvis",
            "LeftShoulder", "LeftUpperArm", "LeftForearm", "LeftHand", "LeftThigh", "LeftLowerLeg", "LeftFoot",
            "RightShoulder", "RightUpperArm", "RightForearm", "RightHand", "RightThigh", "RightLowerLeg", "RightFoot",
        };

        static readonly Dictionary<string, string> RegionBone = new Dictionary<string, string>
        {
            { "Head", "Head" }, { "Neck", "Neck" }, { "Chest", "UpperChest" }, { "Back", "UpperChest" }, { "Abdomen", "Spine" }, { "Pelvis", "Hips" },
        };

        public static ForgeManifest.HitboxEntry[] Hitboxes()
        {
            return ZombieRegions.Select(r =>
            {
                string bone = RegionBone.TryGetValue(r, out var b) ? b : r.Replace("Forearm", "LowerArm").Replace("Thigh", "UpperLeg");
                return new ForgeManifest.HitboxEntry { region = r, bone = bone, radius_m = 0.05f, length_m = 0.2f,
                    side = r == "Chest" ? "front" : r == "Back" ? "back" : null };
            }).ToArray();
        }

        public static ForgeManifest.GoreEntry[] Gore()
        {
            return new[]
            {
                ("Head", "Head"), ("LeftArm", "LeftUpperArm"), ("LeftForearm", "LeftLowerArm"), ("RightArm", "RightUpperArm"),
                ("RightForearm", "RightLowerArm"), ("LeftLeg", "LeftUpperLeg"), ("LeftShin", "LeftLowerLeg"), ("RightLeg", "RightUpperLeg"),
                ("RightShin", "RightLowerLeg"),
            }.Select(p => new ForgeManifest.GoreEntry { part = p.Item1, bone = p.Item2 }).ToArray();
        }
    }
}
