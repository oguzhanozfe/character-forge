using System;
using UnityEngine;

namespace CharacterForge
{
    // Spins the preview character.
    public sealed class ForgeTurntable : MonoBehaviour
    {
        public float degreesPerSecond = 30;
        void Update() => transform.Rotate(0, degreesPerSecond * Time.deltaTime, 0, Space.World);
    }
}
