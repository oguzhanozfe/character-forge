using System;
using UnityEngine;

namespace CharacterForge
{
    // Shared motion library: author motions once, reuse them on every character through its own Humanoid Avatar.
    [CreateAssetMenu(menuName = "Character Forge/Motion Library")]
    public sealed class ForgeMotionLibrary : ScriptableObject
    {
        [Serializable]
        public sealed class Entry
        {
            public string id;
            public string kind;          // Idle, Walk, Run, Attack, Hit, Death, ...
            public string region;        // hit region for Hit entries
            public AnimationClip clip;
            public bool loop;
            [Min(0.01f)] public float weight = 1;
            public float impactSeconds;
            public float suggestedSpeed;
            public string licence;
        }

        public Entry[] entries = Array.Empty<Entry>();

        public Entry Find(string kind, string region = null)
        {
            foreach (var e in entries)
                if (e != null && e.kind == kind && (string.IsNullOrEmpty(region) || e.region == region))
                    return e;
            return null;
        }

        public int Count(string kind)
        {
            int n = 0;
            foreach (var e in entries) if (e != null && e.kind == kind) n++;
            return n;
        }
    }
}
