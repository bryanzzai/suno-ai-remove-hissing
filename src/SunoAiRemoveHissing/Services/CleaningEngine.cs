namespace SunoAiRemoveHissing.Services;

public sealed class CleaningEngine
{
    public Task RunAsync(string pythonPath, string scriptPath, string inputRoot, string outputRoot, int strength,
        double blend, int segment, bool tinCanTest, bool overwrite, IProgress<string>? output, CancellationToken cancellationToken)
    {
        if (!File.Exists(pythonPath)) throw new FileNotFoundException("Choose a valid Python executable.", pythonPath);
        if (!File.Exists(scriptPath)) throw new FileNotFoundException("The bundled SunoClean backend is missing.", scriptPath);

        var arguments = new List<string>
        {
            scriptPath,
            "--input-root", inputRoot,
            "--output-root", outputRoot,
            "--strength", strength.ToString(System.Globalization.CultureInfo.InvariantCulture),
            "--blend", blend.ToString(System.Globalization.CultureInfo.InvariantCulture),
            "--segment", segment.ToString(System.Globalization.CultureInfo.InvariantCulture)
        };
        if (tinCanTest) arguments.Add("--tin-can-test");
        if (overwrite) arguments.Add("--force");
        return ProcessRunner.RunAsync(pythonPath, arguments, output, cancellationToken);
    }
}
