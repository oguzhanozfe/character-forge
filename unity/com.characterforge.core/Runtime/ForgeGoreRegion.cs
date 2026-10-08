using System;
using UnityEngine;

namespace CharacterForge
{
    // A severable gore region: the bone where the limb separates, plus the baked gib (limb piece) and stump cap meshes.
    [DisallowMultipleComponent]
    public sealed class ForgeGoreRegion : MonoBehaviour
    {
        public string part;
        public Transform cutBone;
        public Mesh gibMesh;
        public Mesh stumpMesh;
    }
}
