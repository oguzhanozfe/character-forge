using System;
using UnityEngine;

namespace CharacterForge
{
    // Root marker for an imported character: identity plus the motion library it plays.
    [DisallowMultipleComponent]
    public sealed class ForgeCharacter : MonoBehaviour
    {
        public string characterId;
        public string preset;
        public float heightMetres;
        public ForgeMotionLibrary motionLibrary;
    }
}
