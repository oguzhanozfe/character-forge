using System;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace CharacterForge.Editor
{
    // Batchmode entry used by character-forge's unity-import stage:
    //   Unity -batchmode -quit -projectPath <project> -executeMethod CharacterForge.Editor.ForgeBatch.ImportCandidate
    //         -forgeCandidate Assets/CharacterForge/Candidates/<id> -forgeReport <report.json> -logFile <log>
    public static class ForgeBatch
    {
        public static void ImportCandidate()
        {
            string candidate = Argument("-forgeCandidate");
            string reportPath = Argument("-forgeReport");
            int code = 0;
            ForgeImportReport report;
            try
            {
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
                string manifestPath = candidate.TrimEnd('/') + "/character.manifest.json";
                var manifest = ForgeManifest.Parse(File.ReadAllText(manifestPath));
                var prefab = CharacterImporter.Import(manifestPath);
                report = CharacterValidator.Validate(prefab, manifest, AssetDatabase.GetAssetPath(prefab));
                code = report.errors.Length == 0 ? 0 : 1;
            }
            catch (Exception error)
            {
                Debug.LogException(error);
                report = new ForgeImportReport { unity_version = Application.unityVersion, errors = new[] { error.GetType().Name + ": " + error.Message } };
                code = 1;
            }
            if (!string.IsNullOrEmpty(reportPath))
                File.WriteAllText(reportPath, JsonUtility.ToJson(report, true));
            EditorApplication.Exit(code);
        }

        static string Argument(string name)
        {
            var args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
                if (args[i] == name) return args[i + 1];
            throw new ArgumentException("Missing command line argument " + name);
        }
    }
}
