using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace CharacterForge.Editor
{
    // Imports a character-forge package that has been copied under Assets/: configures the model as Humanoid with the
    // manifest's exact bone map (its own Avatar), builds a material from the runtime textures, imports motion clips with
    // that Avatar, creates the motion library + controller, adds regional hitboxes and gore regions, saves a prefab.
    public static class CharacterImporter
    {
        [MenuItem("Tools/Character Forge/Import Packaged Character...")]
        static void ImportMenu()
        {
            string path = EditorUtility.OpenFilePanel("character.manifest.json inside Assets/", Application.dataPath, "json");
            if (string.IsNullOrEmpty(path)) return;
            string project = Path.GetFullPath(Path.Combine(Application.dataPath, "..")).Replace('\\', '/');
            path = Path.GetFullPath(path).Replace('\\', '/');
            if (!path.StartsWith(project + "/Assets/"))
            {
                EditorUtility.DisplayDialog("Character Forge", "Copy the package folder under Assets/ first.", "OK");
                return;
            }
            var prefab = Import(path.Substring(project.Length + 1));
            Selection.activeObject = prefab;
            EditorGUIUtility.PingObject(prefab);
        }

        public static GameObject Import(string manifestAssetPath)
        {
            manifestAssetPath = manifestAssetPath.Replace('\\', '/');
            string folder = Path.GetDirectoryName(manifestAssetPath).Replace('\\', '/');
            var manifest = ForgeManifest.Parse(File.ReadAllText(manifestAssetPath));
            if (manifest.mode == "fake")
                throw new InvalidOperationException("This is a fake-mode package (placeholder FBX). Run the pipeline in real mode first.");
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            string modelPath = folder + "/" + manifest.model;
            var avatar = ConfigureModel(modelPath, manifest);
            var material = BuildMaterial(folder, manifest);
            var library = ImportMotions(folder, manifest, avatar);
            var controller = library.entries.Length > 0 ? MotionLibraryTools.BuildController(library, folder + "/" + manifest.id + "_Motions.controller") : null;

            var model = AssetDatabase.LoadAssetAtPath<GameObject>(modelPath);
            var root = (GameObject)PrefabUtility.InstantiatePrefab(model);
            try
            {
                root.name = manifest.id;
                var animator = root.GetComponent<Animator>() ?? root.AddComponent<Animator>();
                animator.avatar = avatar;
                animator.applyRootMotion = false;
                animator.cullingMode = AnimatorCullingMode.CullUpdateTransforms;
                foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
                    renderer.sharedMaterials = Enumerable.Repeat(material, Math.Max(1, renderer.sharedMaterials.Length)).ToArray();
                var marker = root.AddComponent<ForgeCharacter>();
                marker.characterId = manifest.id;
                marker.preset = manifest.preset;
                marker.heightMetres = manifest.height_m;
                MotionLibraryTools.Apply(root, library, controller);
                HitboxBuilder.Build(root, manifest.hitboxes);
                GoreBaker.Build(root, manifest.gore, folder + "/Gore");
                string prefabPath = folder + "/" + manifest.id + ".prefab";
                PrefabUtility.UnpackPrefabInstance(root, PrefabUnpackMode.OutermostRoot, InteractionMode.AutomatedAction);
                var prefab = PrefabUtility.SaveAsPrefabAsset(root, prefabPath);
                AssetDatabase.SaveAssets();
                return prefab;
            }
            finally
            {
                Object.DestroyImmediate(root);
            }
        }

        static Avatar ConfigureModel(string modelPath, ForgeManifest manifest)
        {
            var importer = (ModelImporter)AssetImporter.GetAtPath(modelPath) ??
                           throw new FileNotFoundException("Model not imported: " + modelPath);
            importer.useFileScale = true;
            importer.globalScale = 1f;
            importer.importAnimation = false;
            importer.importCameras = false;
            importer.importLights = false;
            importer.materialImportMode = ModelImporterMaterialImportMode.None;
            importer.isReadable = true;
            importer.optimizeGameObjects = false;
            importer.skinWeights = ModelImporterSkinWeights.Standard;
            importer.animationType = ModelImporterAnimationType.Generic;
            importer.SaveAndReimport();
            var model = AssetDatabase.LoadAssetAtPath<GameObject>(modelPath);
            importer.humanDescription = ForgeRig.Describe(model.transform, manifest.humanoid);
            importer.animationType = ModelImporterAnimationType.Human;
            importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
            importer.SaveAndReimport();
            var avatar = AssetDatabase.LoadAllAssetsAtPath(modelPath).OfType<Avatar>().FirstOrDefault();
            if (!avatar || !avatar.isValid || !avatar.isHuman)
                Debug.LogError("Character Forge: Avatar for " + modelPath + " is not a valid Humanoid; check the bone map in the manifest.");
            return avatar;
        }

        static Material BuildMaterial(string folder, ForgeManifest manifest)
        {
            var urp = Shader.Find("Universal Render Pipeline/Lit");
            var shader = urp ? urp : Shader.Find("Standard");
            string path = folder + "/" + manifest.id + "_Body.mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (!material)
            {
                material = new Material(shader) { name = manifest.id + "_Body" };
                AssetDatabase.CreateAsset(material, path);
            }
            material.shader = shader;
            var entries = manifest.materials.Length > 0 ? manifest.materials[0].textures : Array.Empty<ForgeManifest.TextureEntry>();
            foreach (var t in entries)
            {
                string texturePath = folder + "/" + t.file;
                if (AssetImporter.GetAtPath(texturePath) is TextureImporter ti)
                {
                    ti.textureType = t.channel == "Normal" ? TextureImporterType.NormalMap : TextureImporterType.Default;
                    ti.sRGBTexture = t.channel == "BaseColor";
                    ti.alphaSource = t.channel == "MetallicSmoothness" ? TextureImporterAlphaSource.FromInput : ti.alphaSource;
                    ti.SaveAndReimport();
                }
                var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(texturePath);
                if (!texture) continue;
                switch (t.channel)
                {
                    case "BaseColor":
                        material.SetTexture(urp ? "_BaseMap" : "_MainTex", texture);
                        break;
                    case "Normal":
                        material.SetTexture("_BumpMap", texture);
                        material.EnableKeyword("_NORMALMAP");
                        break;
                    case "MetallicSmoothness":
                        material.SetTexture("_MetallicGlossMap", texture);
                        material.EnableKeyword(urp ? "_METALLICSPECGLOSSMAP" : "_METALLICGLOSSMAP");
                        break;
                }
            }
            EditorUtility.SetDirty(material);
            return material;
        }

        static ForgeMotionLibrary ImportMotions(string folder, ForgeManifest manifest, Avatar avatar)
        {
            var entries = new List<ForgeMotionLibrary.Entry>();
            foreach (var motion in manifest.motions)
            {
                string path = folder + "/" + motion.file;
                if (!(AssetImporter.GetAtPath(path) is ModelImporter importer)) continue;
                importer.animationType = ModelImporterAnimationType.Human;
                importer.avatarSetup = ModelImporterAvatarSetup.CopyFromOther;
                importer.sourceAvatar = avatar;
                importer.importAnimation = true;
                importer.materialImportMode = ModelImporterMaterialImportMode.None;
                var clips = importer.defaultClipAnimations;
                foreach (var clip in clips)
                {
                    clip.name = motion.id;
                    clip.loopTime = motion.loop;
                    clip.loopPose = motion.loop;
                    clip.lockRootRotation = true;
                    clip.lockRootHeightY = false;
                    clip.keepOriginalOrientation = true;
                    clip.keepOriginalPositionY = true;
                    clip.keepOriginalPositionXZ = true;
                }
                importer.clipAnimations = clips;
                importer.SaveAndReimport();
                var animation = AssetDatabase.LoadAllAssetsAtPath(path).OfType<AnimationClip>().FirstOrDefault(c => !c.name.StartsWith("__preview__"));
                if (!animation) continue;
                entries.Add(new ForgeMotionLibrary.Entry
                {
                    id = motion.id, kind = motion.kind, region = motion.region, clip = animation, loop = motion.loop,
                    impactSeconds = motion.impact_seconds, suggestedSpeed = motion.suggested_speed_m_s, licence = motion.licence
                });
            }
            return MotionLibraryTools.CreateLibrary(folder + "/" + manifest.id + "_Motions.asset", entries);
        }
    }
}
