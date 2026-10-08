namespace PicotooPet.TextOverlayCompatibilityProbe;

/// <summary>One closed-list font: file name under the Windows Fonts folder and its ASS family name.</summary>
internal sealed record FontCandidate(string FileName, string Family);

internal sealed record ResolvedFont(FontCandidate Candidate, string FullPath, byte[] Bytes);

/// <summary>
/// Closed internal candidate list resolved only under the system Fonts folder. There is no caller-provided
/// font path, family or directory; the chosen file is copied into the probe-managed temp directory.
/// </summary>
internal static class FontPolicy
{
    // Order is the frozen preference order; CJK-capable fonts first for the Chinese overlay.
    public static readonly IReadOnlyList<FontCandidate> ChineseCandidates =
    [
        new("msyh.ttc", "Microsoft YaHei"),
        new("Deng.ttf", "DengXian"),
        new("simhei.ttf", "SimHei"),
        new("simsun.ttc", "SimSun"),
    ];

    public static readonly IReadOnlyList<FontCandidate> EnglishCandidates =
    [
        new("arial.ttf", "Arial"),
        new("segoeui.ttf", "Segoe UI"),
        new("msyh.ttc", "Microsoft YaHei"),
    ];

    public static string FontsDirectory() => Environment.GetFolderPath(Environment.SpecialFolder.Fonts);

    public static IReadOnlyList<string> FoundCandidateNames(bool simulateNoFont) =>
        simulateNoFont
            ? []
            : ChineseCandidates.Concat(EnglishCandidates)
                .Select(candidate => candidate.FileName)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .Where(name => File.Exists(Path.Combine(FontsDirectory(), name)))
                .ToList();

    /// <summary>First candidate that exists, is an ordinary file, and covers every glyph of the text.</summary>
    public static (ResolvedFont? Font, string Status) Resolve(
        IReadOnlyList<FontCandidate> candidates,
        string text,
        bool simulateNoFont)
    {
        if (simulateNoFont)
        {
            return (null, Status.FontUnavailable);
        }
        var sawFont = false;
        foreach (var candidate in candidates)
        {
            var path = Path.Combine(FontsDirectory(), candidate.FileName);
            if (!File.Exists(path) || (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            {
                continue;
            }
            sawFont = true;
            var info = new FileInfo(path);
            if (info.Length is <= 0 or > 64L * 1024 * 1024)
            {
                continue;
            }
            var bytes = File.ReadAllBytes(path);
            if (SfntCmap.TryCovers(bytes, text, out var covers) && covers)
            {
                return (new ResolvedFont(candidate, path, bytes), Status.Pass);
            }
        }
        return (null, sawFont ? Status.GlyphMissing : Status.FontUnavailable);
    }

    /// <summary>Negative control: Chinese text against the Latin-only first English candidate must fail preflight.</summary>
    public static string CheckMissingGlyphDetection()
    {
        var latin = EnglishCandidates[0];
        var path = Path.Combine(FontsDirectory(), latin.FileName);
        if (!File.Exists(path))
        {
            return Status.NotRun;
        }
        var bytes = File.ReadAllBytes(path);
        return SfntCmap.TryCovers(bytes, Profile.ChineseText, out var covers) && !covers
            ? "GLYPH_MISSING_DETECTED"
            : "GLYPH_MISSING_NOT_DETECTED";
    }
}
