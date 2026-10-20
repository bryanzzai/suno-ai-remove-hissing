namespace SunoAiRemoveHissing.Services;

public sealed class CleaningEngine
{
    public async Task RunAsync(string pythonPath, string scriptPath, string inputRoot, string outputRoot,
        IEnumerable<string> selectedRelativePaths, bool dynamicFullMixTest, bool harmonicDeFizzer, bool overwrite,
        IProgress<string>? output, CancellationToken cancellationToken)
    {
        if (!File.Exists(pythonPath)) throw new FileNotFoundException("Choose a valid Python executable.", pythonPath);
        if (!File.Exists(scriptPath)) throw new FileNotFoundException("The bundled SunoClean backend is missing.", scriptPath);
        var selected = selectedRelativePaths.Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        if (selected.Length == 0) throw new InvalidOperationException("No audio files were selected.");
        var manifestPath = Path.Combine(Path.GetTempPath(), $"sunoclean-selected-{Guid.NewGuid():N}.txt");
        await File.WriteAllLinesAsync(manifestPath, selected, cancellationToken);

        try
        {
            var arguments = new List<string>
            {
                scriptPath,
                "--input-root", inputRoot,
                "--output-root", outputRoot,
                "--selected-list", manifestPath
            };
            if (dynamicFullMixTest) arguments.Add("--dynamic-full-mix-test");
            if (harmonicDeFizzer) arguments.Add("--harmonic-de-fizzer");
            if (overwrite) arguments.Add("--force");
            await ProcessRunner.RunAsync(pythonPath, arguments, output, cancellationToken);
        }
        finally
        {
            if (File.Exists(manifestPath)) File.Delete(manifestPath);
        }
    }
}
