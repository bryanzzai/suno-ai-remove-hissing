using System.Diagnostics;
using System.IO;

namespace SunoAiRemoveHissing.Services;

public static class ProcessRunner
{
    public static async Task RunAsync(string executable, IEnumerable<string> arguments, IProgress<string>? output,
        CancellationToken cancellationToken)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        foreach (var argument in arguments)
            startInfo.ArgumentList.Add(argument);

        using var process = new Process { StartInfo = startInfo };
        if (!process.Start())
            throw new InvalidOperationException($"Could not start {Path.GetFileName(executable)}.");

        var stdout = PumpAsync(process.StandardOutput, output);
        var stderr = PumpAsync(process.StandardError, output);
        using var registration = cancellationToken.Register(() => Kill(process));
        await process.WaitForExitAsync(cancellationToken);
        await Task.WhenAll(stdout, stderr);

        if (process.ExitCode != 0)
            throw new InvalidOperationException($"The cleaning engine stopped with exit code {process.ExitCode}.");
    }

    private static async Task PumpAsync(StreamReader reader, IProgress<string>? output)
    {
        while (await reader.ReadLineAsync() is { } line)
            output?.Report(line);
    }

    private static void Kill(Process process)
    {
        try
        {
            if (!process.HasExited)
                process.Kill(entireProcessTree: true);
        }
        catch (InvalidOperationException) { }
    }
}
