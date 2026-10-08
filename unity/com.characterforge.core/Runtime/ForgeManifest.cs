using System;

namespace CharacterForge
{
    // Mirrors character.manifest.json (format character-forge/manifest@1). Arrays only, so JsonUtility can read it.
    [Serializable]
    public sealed class ForgeManifest
    {
        public string format;
        public string id;
        public string preset;
        public float height_m;
        public string mode;
        public string model;
        public MaterialEntry[] materials = Array.Empty<MaterialEntry>();
        public HumanEntry[] humanoid = Array.Empty<HumanEntry>();
        public string[] required_bones = Array.Empty<string>();
        public string[] helpers = Array.Empty<string>();
        public HitboxEntry[] hitboxes = Array.Empty<HitboxEntry>();
        public GoreEntry[] gore = Array.Empty<GoreEntry>();
        public MotionEntry[] motions = Array.Empty<MotionEntry>();

        public const string Format = "character-forge/manifest@1";

        [Serializable] public sealed class MaterialEntry { public string name; public TextureEntry[] textures = Array.Empty<TextureEntry>(); }
        [Serializable] public sealed class TextureEntry { public string channel; public string file; }
        [Serializable] public sealed class HumanEntry { public string human; public string bone; }
        [Serializable] public sealed class HitboxEntry { public string region; public string bone; public string side; public float radius_m; public float length_m; public int vertices; }
        [Serializable] public sealed class GoreEntry { public string part; public string bone; }
        [Serializable] public sealed class MotionEntry
        {
            public string id;
            public string kind;
            public string region;
            public string file;
            public bool loop;
            public float impact_seconds;
            public float suggested_speed_m_s;
            public string licence;
        }

        public static ForgeManifest Parse(string json)
        {
            var manifest = UnityEngine.JsonUtility.FromJson<ForgeManifest>(json);
            if (manifest == null || manifest.format != Format)
                throw new FormatException("Not a character-forge manifest (expected format " + Format + ")");
            return manifest;
        }
    }
}
