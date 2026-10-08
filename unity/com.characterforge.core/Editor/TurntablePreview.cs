using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace CharacterForge.Editor
{
    // A neutral review scene: ground, light, camera and the selected character spinning while it cycles its motions.
    public static class TurntablePreview
    {
        [MenuItem("Tools/Character Forge/Turntable Preview (Selected Prefab)")]
        public static void Open()
        {
            var prefab = Selection.activeObject as GameObject;
            if (!prefab || !PrefabUtility.IsPartOfPrefabAsset(prefab))
            {
                EditorUtility.DisplayDialog("Character Forge", "Select an imported character prefab asset first.", "OK");
                return;
            }
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            Build(prefab);
        }

        public static GameObject Build(GameObject prefab)
        {
            EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
            var ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
            ground.name = "Ground";
            ground.transform.localScale = new Vector3(0.4f, 1, 0.4f);
            var character = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            var marker = character.GetComponent<ForgeCharacter>();
            float height = marker && marker.heightMetres > 0 ? marker.heightMetres : 1.8f;
            var forward = ForgeRig.Forward(character.transform);
            var pivot = new GameObject("Turntable");
            character.transform.SetParent(pivot.transform, true);
            pivot.AddComponent<ForgeTurntable>();
            var animator = character.GetComponentInChildren<Animator>();
            if (animator && marker && marker.motionLibrary)
            {
                var preview = animator.gameObject.GetComponent<ForgeMotionPreview>() ?? animator.gameObject.AddComponent<ForgeMotionPreview>();
                preview.library = marker.motionLibrary;
            }
            var camera = Camera.main;
            if (camera)
            {
                camera.transform.position = forward * (height * 2.2f) + Vector3.up * (height * 0.55f);
                camera.transform.LookAt(Vector3.up * (height * 0.5f));
                camera.backgroundColor = new Color(0.14f, 0.15f, 0.17f);
                camera.clearFlags = CameraClearFlags.SolidColor;
            }
            Selection.activeGameObject = character;
            return character;
        }
    }
}
