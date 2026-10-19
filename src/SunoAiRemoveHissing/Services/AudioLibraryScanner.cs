using SunoAiRemoveHissing.Models;

namespace SunoAiRemoveHissing.Services;

public sealed class AudioLibraryScanner
{
    private static readonly HashSet<string> Extensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".aiff", ".aif"
    };

    public IReadOnlyList<AudioItem> Scan(string inputRoot, string outputRoot, CancellationToken cancellationToken)
    {
        if (!Directory.Exists(inputRoot))
            throw new DirectoryNotFoundException(inputRoot);

        var normalizedOutput = Path.GetFullPath(outputRoot)
            .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
        var items = new List<AudioItem>();

        foreach (var path in Directory.EnumerateFiles(inputRoot, "*", SearchOption.AllDirectories))
        {
            cancellationToken.ThrowIfCancellationRequested();
            var fullPath = Path.GetFullPath(path);
            if (fullPath.StartsWith(normalizedOutput, StringComparison.OrdinalIgnoreCase) ||
                !Extensions.Contains(Path.GetExtension(fullPath)))
                continue;

            var relative = Path.GetRelativePath(inputRoot, fullPath);
            items.Add(new AudioItem
            {
                FullPath = fullPath,
                RelativePath = relative,
                FileName = Path.GetFileName(fullPath),
                Folder = Path.GetDirectoryName(relative) ?? string.Empty
            });
        }

        return items.OrderBy(x => x.RelativePath, StringComparer.OrdinalIgnoreCase).ToArray();
    }
}
