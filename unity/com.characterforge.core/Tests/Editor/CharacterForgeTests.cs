using System.Collections.Generic;
using System.IO;
using System.Linq;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;

namespace CharacterForge.Editor.Tests
{
    public sealed class AvatarMappingTests
    {
        [Test]
        public void ContractSkeletonBuildsValidHumanoidAvatarWithAll52Bones()
        {
            var root = TestRig.Build();
            try
            {
                var animator = TestRig.WithAvatar(root, TestRig.Mapping(root));
                Assert.IsTrue(animator.avatar.isValid, "avatar valid");
                Assert.IsTrue(animator.avatar.isHuman, "avatar human");
                Assert.AreEqual(52, CharacterValidator.MappedHumanBones(animator));
                var required = System.Enum.GetNames(typeof(HumanBodyBones)).Where(n => n != "LastBone" && ForgeRig.FindDeep(root.transform, n));
                CollectionAssert.IsEmpty(CharacterValidator.MissingRequired(animator, required));
            }
            finally { Object.DestroyImmediate(root); }
        }

        [Test]
        public void MissingHandMappingIsReported()
        {
            var root = TestRig.Build();
            try
            {
                var animator = TestRig.WithAvatar(root, TestRig.Mapping(root, "LeftIndexDistal"));
                var missing = CharacterValidator.MissingRequired(animator, new[] { "LeftIndexDistal", "Hips" });
                CollectionAssert.Contains(missing, "LeftIndexDistal");
                CollectionAssert.DoesNotContain(missing, "Hips");
            }
            finally { Object.DestroyImmediate(root); }
        }

        [Test]
        public void UnknownHumanNamesAreIgnoredByTheMapping()
        {
            var root = TestRig.Build();
            try
            {
                var mapping = TestRig.Mapping(root).Concat(new[] { new ForgeManifest.HumanEntry { human = "NotABone", bone = "Hips" } }).ToArray();
                var description = ForgeRig.Describe(root.transform, mapping);
                Assert.AreEqual(52, description.human.Length);
                Assert.AreEqual(ForgeRig.Walk(root.transform).Count(), description.skeleton.Length);
            }
            finally { Object.DestroyImmediate(root); }
        }
    }

    public sealed class MotionLibraryTests
    {
        static AnimationClip WaveClip()
        {
            var clip = new AnimationClip { name = "Wave" };
            string path = "Hips/Spine/Chest/UpperChest/LeftShoulder/LeftUpperArm";
            var q = Quaternion.Euler(0, 0, 60);
            clip.SetCurve(path, typeof(Transform), "localRotation.x", AnimationCurve.Linear(0, 0, 1, q.x));
            clip.SetCurve(path, typeof(Transform), "localRotation.y", AnimationCurve.Linear(0, 0, 1, q.y));
            clip.SetCurve(path, typeof(Transform), "localRotation.z", AnimationCurve.Linear(0, 0, 1, q.z));
            clip.SetCurve(path, typeof(Transform), "localRotation.w", AnimationCurve.Linear(0, 1, 1, q.w));
            return clip;
        }

        [Test]
        public void LibraryPlaybackMovesBonesAndRestoresBindPose()
        {
            var root = TestRig.Build();
            root.AddComponent<Animator>();
            var library = ScriptableObject.CreateInstance<ForgeMotionLibrary>();
            library.entries = new[] { new ForgeMotionLibrary.Entry { id = "Wave_01", kind = "Idle", clip = WaveClip(), loop = true } };
            try
            {
                var arm = ForgeRig.FindDeep(root.transform, "LeftUpperArm");
                var before = arm.localRotation;
                var errors = CharacterValidator.ValidatePlayback(root, library, out int playable);
                CollectionAssert.IsEmpty(errors);
                Assert.AreEqual(1, playable);
                Assert.AreEqual(0f, Quaternion.Angle(before, arm.localRotation), 1e-3f, "bind pose restored after sampling");
                Assert.AreSame(library.entries[0], library.Find("Idle"));
                Assert.AreEqual(1, library.Count("Idle"));
            }
            finally
            {
                Object.DestroyImmediate(root);
                Object.DestroyImmediate(library);
            }
        }

        [Test]
        public void EmptyEntriesAreReported()
        {
            var root = TestRig.Build();
            root.AddComponent<Animator>();
            var library = ScriptableObject.CreateInstance<ForgeMotionLibrary>();
            library.entries = new[] { new ForgeMotionLibrary.Entry { id = "Broken", kind = "Walk" } };
            try
            {
                var errors = CharacterValidator.ValidatePlayback(root, library, out int playable);
                Assert.AreEqual(0, playable);
                Assert.IsTrue(errors.Any(e => e.Contains("Broken")));
            }
            finally
            {
                Object.DestroyImmediate(root);
                Object.DestroyImmediate(library);
            }
        }

        [Test]
        public void ControllerHasOneStatePerEntryWithIdleDefault()
        {
            const string folder = "Assets/CharacterForgeTestTemp";
            Directory.CreateDirectory(folder);
            var library = ScriptableObject.CreateInstance<ForgeMotionLibrary>();
            var clip = WaveClip();
            library.entries = new[]
            {
                new ForgeMotionLibrary.Entry { id = "Walk_01", kind = "Walk", clip = clip },
                new ForgeMotionLibrary.Entry { id = "Idle_01", kind = "Idle", clip = clip },
            };
            try
            {
                var controller = MotionLibraryTools.BuildController(library, folder + "/Test.controller");
                var states = controller.layers[0].stateMachine.states.Select(s => s.state.name).ToArray();
                CollectionAssert.AreEquivalent(new[] { "Walk_01", "Idle_01" }, states);
                Assert.AreEqual("Idle_01", controller.layers[0].stateMachine.defaultState.name);
            }
            finally
            {
                AssetDatabase.DeleteAsset(folder);
                Object.DestroyImmediate(library);
            }
        }
    }

    public sealed class HitboxAndGoreTests
    {
        [Test]
        public void TwentyRegionalHitboxesAreBuiltUnderTheirBones()
        {
            var root = TestRig.Build();
            try
            {
                int built = HitboxBuilder.Build(root, TestRig.Hitboxes());
                Assert.AreEqual(20, built);
                CollectionAssert.IsEmpty(CharacterValidator.ValidateHitboxes(root, TestRig.ZombieRegions));
                var chest = root.GetComponentsInChildren<ForgeHitbox>().Single(h => h.region == "Chest").transform.position;
                var back = root.GetComponentsInChildren<ForgeHitbox>().Single(h => h.region == "Back").transform.position;
                Assert.Greater(Vector3.Dot(chest - back, ForgeRig.Forward(root.transform)), 0f, "Chest box is in front of Back box");
            }
            finally { Object.DestroyImmediate(root); }
        }

        [Test]
        public void MissingRegionIsReported()
        {
            var root = TestRig.Build();
            try
            {
                HitboxBuilder.Build(root, TestRig.Hitboxes().Where(h => h.region != "LeftFoot").ToArray());
                CollectionAssert.Contains(CharacterValidator.ValidateHitboxes(root, TestRig.ZombieRegions), "missing hitbox region LeftFoot");
            }
            finally { Object.DestroyImmediate(root); }
        }

        [Test]
        public void NineGoreRegionsArePresent()
        {
            var root = TestRig.Build();
            try
            {
                Assert.AreEqual(9, GoreBaker.Build(root, TestRig.Gore()));
                CollectionAssert.IsEmpty(CharacterValidator.ValidateGore(root, TestRig.Gore().Select(g => g.part), requireMeshes: false));
                CollectionAssert.IsNotEmpty(CharacterValidator.ValidateGore(root, new[] { "Tail" }, requireMeshes: false));
            }
            finally { Object.DestroyImmediate(root); }
        }
    }

    // Validates every real (non-fake) packaged character imported into this project. Ignored when there are none.
    public sealed class PackagedCharacterTests
    {
        static IEnumerable<string> Manifests() =>
            AssetDatabase.FindAssets("character.manifest t:TextAsset").Select(AssetDatabase.GUIDToAssetPath)
                .Where(p => p.EndsWith("character.manifest.json"));

        [Test]
        public void ImportedCharactersPassAvatarHitboxGoreAndPlaybackChecks()
        {
            var checkedAny = false;
            foreach (var path in Manifests())
            {
                var manifest = ForgeManifest.Parse(File.ReadAllText(path));
                if (manifest.mode == "fake") continue;
                var prefabPath = Path.GetDirectoryName(path).Replace('\\', '/') + "/" + manifest.id + ".prefab";
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
                if (!prefab) continue;
                var report = CharacterValidator.Validate(prefab, manifest, prefabPath);
                CollectionAssert.IsEmpty(report.errors, manifest.id + ": " + string.Join("; ", report.errors));
                Assert.IsTrue(report.avatar_human, manifest.id + " avatar");
                Assert.AreEqual(manifest.hitboxes.Length, report.hitboxes, manifest.id + " hitboxes");
                Assert.AreEqual(manifest.gore.Length, report.gore_regions, manifest.id + " gore regions");
                Assert.AreEqual(report.motions, report.motions_playable, manifest.id + " playable motions");
                checkedAny = true;
            }
            if (!checkedAny) Assert.Ignore("No imported real character packages in this project yet.");
        }
    }
}
