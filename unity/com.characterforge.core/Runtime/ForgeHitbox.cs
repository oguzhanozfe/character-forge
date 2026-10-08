using System;
using UnityEngine;

namespace CharacterForge
{
    // One regional hitbox (collider on a child of the bone). Region names come from the preset (e.g. Head, LeftForearm).
    [DisallowMultipleComponent]
    public sealed class ForgeHitbox : MonoBehaviour
    {
        public string region;
        public Transform bone;
    }
}
