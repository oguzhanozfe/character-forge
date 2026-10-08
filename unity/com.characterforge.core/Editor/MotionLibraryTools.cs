using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace CharacterForge.Editor
{
    // Shared motion library -> Animator controller (one state per entry, state name = entry id) and application to
    // characters. Plug in your own library: create a ForgeMotionLibrary asset that lists your Humanoid clips
    // (Assets > Create > Character Forge > Motion Library), then Tools > Character Forge > Apply Motion Library.
    public static class MotionLibraryTools
    {
        public static ForgeMotionLibrary CreateLibrary(string assetPath, IEnumerable<ForgeMotionLibrary.Entry> entries)
        {
            var library = AssetDatabase.LoadAssetAtPath<ForgeMotionLibrary>(assetPath);
            if (!library)
            {
                library = ScriptableObject.CreateInstance<ForgeMotionLibrary>();
                AssetDatabase.CreateAsset(library, assetPath);
            }
            library.entries = entries.ToArray();
            EditorUtility.SetDirty(library);
            AssetDatabase.SaveAssets();
            return library;
        }

        public static AnimatorController BuildController(ForgeMotionLibrary library, string assetPath)
        {
            if (File.Exists(assetPath)) AssetDatabase.DeleteAsset(assetPath);
            var controller = AnimatorController.CreateAnimatorControllerAtPath(assetPath);
            var machine = controller.layers[0].stateMachine;
            AnimatorState first = null, idle = null;
            var used = new HashSet<string>();
            foreach (var entry in library.entries)
            {
                if (entry == null || !entry.clip || !used.Add(entry.id)) continue;
                var state = machine.AddState(entry.id);
                state.motion = entry.clip;
                first = first ?? state;
                if (idle == null && entry.kind == "Idle") idle = state;
            }
            if (idle != null || first != null) machine.defaultState = idle ?? first;
            EditorUtility.SetDirty(controller);
            AssetDatabase.SaveAssets();
            return controller;
        }

        public static void Apply(GameObject character, ForgeMotionLibrary library, RuntimeAnimatorController controller)
        {
            var animator = character.GetComponentInChildren<Animator>(true);
            if (animator) animator.runtimeAnimatorController = controller;
            var marker = character.GetComponent<ForgeCharacter>();
            if (marker) marker.motionLibrary = library;
        }

        [MenuItem("Tools/Character Forge/Apply Motion Library To Selected Prefab")]
        static void ApplyToSelection()
        {
            var library = Selection.objects.OfType<ForgeMotionLibrary>().FirstOrDefault();
            var prefab = Selection.objects.OfType<GameObject>().FirstOrDefault(o => PrefabUtility.IsPartOfPrefabAsset(o));
            if (!library || !prefab)
            {
                EditorUtility.DisplayDialog("Character Forge", "Select a ForgeMotionLibrary asset AND a character prefab asset.", "OK");
                return;
            }
            string folder = Path.GetDirectoryName(AssetDatabase.GetAssetPath(library)).Replace('\\', '/');
            var controller = BuildController(library, folder + "/" + library.name + ".controller");
            var path = AssetDatabase.GetAssetPath(prefab);
            var root = PrefabUtility.LoadPrefabContents(path);
            Apply(root, library, controller);
            PrefabUtility.SaveAsPrefabAsset(root, path);
            PrefabUtility.UnloadPrefabContents(root);
            Debug.Log("Character Forge: applied " + library.name + " (" + library.entries.Length + " motions) to " + path);
        }
    }
}
