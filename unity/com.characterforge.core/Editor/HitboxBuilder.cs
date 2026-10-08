using UnityEngine;

namespace CharacterForge.Editor
{
    // Regional capsule hitboxes from the manifest: one child per region under its bone, so they follow the animation.
    public static class HitboxBuilder
    {
        public const string Prefix = "Hitbox_";

        public static int Build(GameObject root, ForgeManifest.HitboxEntry[] entries)
        {
            foreach (var old in root.GetComponentsInChildren<ForgeHitbox>(true))
                Object.DestroyImmediate(old.gameObject);
            var forward = ForgeRig.Forward(root.transform);
            int built = 0;
            foreach (var entry in entries)
            {
                var bone = ForgeRig.FindDeep(root.transform, entry.bone);
                if (!bone) continue;
                ForgeRig.Segment(root.transform, bone, entry.length_m, out var start, out var end);
                float radius = Mathf.Max(0.01f, entry.radius_m > 0 ? entry.radius_m : 0.05f);
                var centre = (start + end) * 0.5f;
                if (entry.side == "front" || entry.side == "back")
                {
                    radius *= 0.75f;
                    centre += forward * (entry.side == "front" ? radius * 0.6f : -radius * 0.6f);
                }
                var box = new GameObject(Prefix + entry.region);
                box.transform.SetParent(bone, false);
                box.transform.position = centre;
                var axis = end - start;
                box.transform.rotation = axis.sqrMagnitude > 1e-10 ? Quaternion.FromToRotation(Vector3.up, axis) : bone.rotation;
                var capsule = box.AddComponent<CapsuleCollider>();
                capsule.direction = 1;
                capsule.radius = radius / Mathf.Max(1e-6f, box.transform.lossyScale.x);
                capsule.height = (axis.magnitude + 2 * radius) / Mathf.Max(1e-6f, box.transform.lossyScale.y);
                var hitbox = box.AddComponent<ForgeHitbox>();
                hitbox.region = entry.region;
                hitbox.bone = bone;
                built++;
            }
            return built;
        }
    }
}
