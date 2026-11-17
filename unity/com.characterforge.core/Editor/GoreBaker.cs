using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace CharacterForge.Editor
{
    // Dismemberment baker: for each gore part, the skinned triangles dominated (>= 50 %
    // weight) by the cut bone's subtree become a loose limb mesh in that bone's space; the cut boundary becomes a cap on
    // the limb (gib) and a reversed stump cap in the parent bone's space. Bind pose only; the saved body is not changed.
    public static class GoreBaker
    {
        public const string Prefix = "Gore_";

        public static int Build(GameObject root, ForgeManifest.GoreEntry[] parts, string assetFolder = null)
        {
            foreach (var old in root.GetComponentsInChildren<ForgeGoreRegion>(true))
                Object.DestroyImmediate(old.gameObject);
            var renderer = root.GetComponentInChildren<SkinnedMeshRenderer>(true);
            int built = 0;
            foreach (var part in parts)
            {
                var bone = ForgeRig.FindDeep(root.transform, part.bone);
                if (!bone) continue;
                var marker = new GameObject(Prefix + part.part);
                marker.transform.SetParent(bone, false);
                var region = marker.AddComponent<ForgeGoreRegion>();
                region.part = part.part;
                region.cutBone = bone;
                if (renderer && renderer.sharedMesh && renderer.sharedMesh.isReadable)
                {
                    BakePart(renderer, bone, out var gib, out var stump);
                    if (gib != null && assetFolder != null)
                    {
                        Directory.CreateDirectory(assetFolder);
                        gib.name = root.name + "_" + part.part + "_Gib";
                        stump.name = root.name + "_" + part.part + "_Stump";
                        AssetDatabase.CreateAsset(gib, assetFolder + "/" + gib.name + ".asset");
                        AssetDatabase.CreateAsset(stump, assetFolder + "/" + stump.name + ".asset");
                    }
                    region.gibMesh = gib;
                    region.stumpMesh = stump;
                }
                built++;
            }
            return built;
        }

        static void BakePart(SkinnedMeshRenderer renderer, Transform cut, out Mesh gib, out Mesh stump)
        {
            gib = stump = null;
            var mesh = renderer.sharedMesh;
            var bones = renderer.bones;
            var inSubtree = new bool[bones.Length];
            for (int b = 0; b < bones.Length; b++) inSubtree[b] = bones[b] && ForgeRig.IsDescendant(bones[b], cut);
            var weights = mesh.boneWeights;
            var share = new float[mesh.vertexCount];
            for (int v = 0; v < weights.Length; v++)
            {
                var w = weights[v];
                share[v] = (inSubtree[w.boneIndex0] ? w.weight0 : 0) + (inSubtree[w.boneIndex1] ? w.weight1 : 0) +
                           (inSubtree[w.boneIndex2] ? w.weight2 : 0) + (inSubtree[w.boneIndex3] ? w.weight3 : 0);
            }
            var baked = new Mesh();
            renderer.BakeMesh(baked, true);
            var world = baked.vertices;
            for (int i = 0; i < world.Length; i++) world[i] = renderer.transform.TransformPoint(world[i]);
            var selected = new List<int>();
            var triangles = mesh.triangles;
            for (int t = 0; t < triangles.Length; t += 3)
                if ((share[triangles[t]] + share[triangles[t + 1]] + share[triangles[t + 2]]) / 3f >= 0.5f)
                    selected.AddRange(new[] { triangles[t], triangles[t + 1], triangles[t + 2] });
            if (selected.Count == 0) return;
            // Boundary of the selection (welded by position so UV seams do not count) -> cap fans.
            var weld = new Dictionary<Vector3Int, int>();
            int Key(int v)
            {
                var p = world[v] * 100000f;
                var k = new Vector3Int(Mathf.RoundToInt(p.x), Mathf.RoundToInt(p.y), Mathf.RoundToInt(p.z));
                if (!weld.TryGetValue(k, out var id)) weld[k] = id = v;
                return id;
            }
            var edgeCount = new Dictionary<(int, int), int>();
            var directed = new Dictionary<(int, int), (int, int)>();
            for (int t = 0; t < selected.Count; t += 3)
                for (int e = 0; e < 3; e++)
                {
                    int a = Key(selected[t + e]), b = Key(selected[t + (e + 1) % 3]);
                    var key = a < b ? (a, b) : (b, a);
                    edgeCount[key] = edgeCount.TryGetValue(key, out var c) ? c + 1 : 1;
                    directed[key] = (a, b);
                }
            var capTriangles = new List<int>();
            var capVertices = new List<Vector3>();
            var next = new Dictionary<int, int>();
            foreach (var pair in edgeCount)
                if (pair.Value == 1) { var d = directed[pair.Key]; next[d.Item2] = d.Item1; }
            var visited = new HashSet<int>();
            foreach (var start in next.Keys)
            {
                if (visited.Contains(start)) continue;
                var loop = new List<int>();
                for (int v = start; !visited.Contains(v) && next.ContainsKey(v); v = next[v]) { visited.Add(v); loop.Add(v); }
                if (loop.Count < 3) continue;
                var centre = Vector3.zero;
                foreach (var v in loop) centre += world[v];
                centre /= loop.Count;
                int baseIndex = capVertices.Count;
                capVertices.Add(centre);
                foreach (var v in loop) capVertices.Add(world[v]);
                for (int i = 0; i < loop.Count; i++)
                    capTriangles.AddRange(new[] { baseIndex, baseIndex + 1 + i, baseIndex + 1 + (i + 1) % loop.Count });
            }
            gib = Assemble(selected, world, mesh.uv, capVertices, capTriangles, cut, false);
            stump = Assemble(new List<int>(), world, null, capVertices, capTriangles, cut.parent ? cut.parent : cut, true);
        }

        static Mesh Assemble(List<int> selected, Vector3[] world, Vector2[] uv, List<Vector3> capVertices, List<int> capTriangles,
                             Transform space, bool flip)
        {
            var remap = new Dictionary<int, int>();
            var vertices = new List<Vector3>();
            var uvs = new List<Vector2>();
            var tris = new List<int>();
            foreach (var v in selected)
            {
                if (!remap.TryGetValue(v, out var id))
                {
                    remap[v] = id = vertices.Count;
                    vertices.Add(space.InverseTransformPoint(world[v]));
                    uvs.Add(uv != null && v < uv.Length ? uv[v] : Vector2.zero);
                }
                tris.Add(id);
            }
            int offset = vertices.Count;
            foreach (var p in capVertices) { vertices.Add(space.InverseTransformPoint(p)); uvs.Add(Vector2.zero); }
            for (int i = 0; i < capTriangles.Count; i += 3)
            {
                if (flip) tris.AddRange(new[] { offset + capTriangles[i], offset + capTriangles[i + 2], offset + capTriangles[i + 1] });
                else tris.AddRange(new[] { offset + capTriangles[i], offset + capTriangles[i + 1], offset + capTriangles[i + 2] });
            }
            var mesh = new Mesh { indexFormat = vertices.Count > 65000 ? UnityEngine.Rendering.IndexFormat.UInt32 : UnityEngine.Rendering.IndexFormat.UInt16 };
            mesh.SetVertices(vertices);
            mesh.SetUVs(0, uvs);
            mesh.SetTriangles(tris, 0);
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            return mesh;
        }
    }
}
