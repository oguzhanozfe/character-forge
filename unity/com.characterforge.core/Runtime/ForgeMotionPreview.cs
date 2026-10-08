using System;
using UnityEngine;

namespace CharacterForge
{
    // Cycles through the library's states on the Animator (state names = entry ids) for visual review.
    [RequireComponent(typeof(Animator))]
    public sealed class ForgeMotionPreview : MonoBehaviour
    {
        public ForgeMotionLibrary library;
        public float secondsPerClip = 3;
        int index;
        float timer;

        void Start() => Play();

        void Update()
        {
            if (!library || library.entries.Length == 0) return;
            timer += Time.deltaTime;
            if (timer < secondsPerClip) return;
            timer = 0;
            index = (index + 1) % library.entries.Length;
            Play();
        }

        void Play()
        {
            if (!library || library.entries.Length == 0) return;
            var animator = GetComponent<Animator>();
            if (animator.runtimeAnimatorController) animator.Play(library.entries[index].id, 0, 0);
        }

        void OnGUI()
        {
            if (library && library.entries.Length > 0)
                GUI.Label(new Rect(12, 12, 600, 24), "Motion " + (index + 1) + "/" + library.entries.Length + ": " + library.entries[index].id);
        }
    }
}
