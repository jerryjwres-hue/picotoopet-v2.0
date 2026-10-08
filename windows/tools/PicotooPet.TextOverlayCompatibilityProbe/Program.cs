using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace PicotooPet.TextOverlayCompatibilityProbe;

/// <summary>
/// S004 compatibility probe. Closed argument set; no font, filter, text, path or executable input exists.
/// Writes only under a probe-managed temp directory that is always removed.
/// </summary>
internal static class Program
{
    private const int MinTimeoutSeconds = 5;
    private const int MaxTimeoutSeconds = 120;
    private const int DefaultTimeoutSeconds = 60;

    public static async Task<int> Main(string[] args)
    {
        if (!TryParse(args, out var selection, out var timeoutSeconds, out var simulateNoFont, out var selfTest))
        {
            Console.Error.WriteLine(
                "INVALID_ARGUMENT usage: [--path drawtext|libass|all] [--timeout-seconds 5..120] " +
                "[--simulate-no-font] [--self-test]");
            return 3;
        }
        if (selfTest)
        {
            return SelfTest();
        }
        if (!OperatingSystem.IsWindows())
        {
            Console.WriteLine(JsonSerializer.Serialize(
                new { probe = "picotoopet.text_overlay_compatibility.s004", status = Status.NotWindows },
                ProbeJson.Options));
            return 1;
        }

        var root = Path.Combine(Path.GetTempPath(), "PicotooPetTextOverlayProbe", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var timeout = TimeSpan.FromSeconds(timeoutSeconds);
            var capabilities = await DetectCapabilitiesAsync(root, timeout).ConfigureAwait(false);

            var reports = new List<PathReport>();
            if (capabilities.Version is null)
            {
                reports.Add(new PathReport("drawtext", Status.FfmpegUnavailable, false, null, null, [], false, false, null, null));
                reports.Add(new PathReport("libass", Status.FfmpegUnavailable, false, null, null, [], false, false, null, null));
            }
            else
            {
                var evaluator = new PathEvaluator(root, capabilities, timeout, simulateNoFont);
                if (selection is "all" or "drawtext")
                {
                    reports.Add(await evaluator.EvaluateAsync(OverlayPath.Drawtext).ConfigureAwait(false));
                }
                if (selection is "all" or "libass")
                {
                    reports.Add(await evaluator.EvaluateAsync(OverlayPath.Libass).ConfigureAwait(false));
                }
            }

            var (zhFont, _) = FontPolicy.Resolve(FontPolicy.ChineseCandidates, Profile.ChineseText, simulateNoFont);
            var (enFont, _) = FontPolicy.Resolve(FontPolicy.EnglishCandidates, Profile.EnglishText, simulateNoFont);
            var (_, missingFontStatus) = FontPolicy.Resolve([], Profile.EnglishText, simulateNoFont: false);
            var report = new ProbeReport(
                "picotoopet.text_overlay_compatibility.s004",
                Environment.OSVersion.VersionString,
                capabilities.Version,
                capabilities.Libass,
                capabilities.Libfreetype,
                capabilities.X264,
                capabilities.FfprobeAvailable,
                timeoutSeconds,
                simulateNoFont,
                new FontPolicyReport(
                    FontPolicy.FoundCandidateNames(simulateNoFont),
                    enFont?.Candidate.FileName,
                    zhFont?.Candidate.FileName,
                    missingFontStatus == Status.FontUnavailable ? "FONT_UNAVAILABLE_DETECTED" : "FONT_UNAVAILABLE_NOT_DETECTED",
                    FontPolicy.CheckMissingGlyphDetection()),
                reports,
                Decide(reports));
            Console.WriteLine(JsonSerializer.Serialize(report, ProbeJson.Options));
            return reports.Any(item => item.Status == Status.Pass) ? 0 : 1;
        }
        finally
        {
            try
            {
                Directory.Delete(root, recursive: true);
            }
            catch (IOException)
            {
                // Best-effort cleanup of the probe-managed directory only.
            }
            catch (UnauthorizedAccessException)
            {
                // Same.
            }
        }
    }

    /// <summary>Suggestion only; the result document states the final decision.</summary>
    private static string Decide(IReadOnlyList<PathReport> reports)
    {
        bool Passed(string name) => reports.Any(item => item.Path == name && item.Status == Status.Pass);
        return Passed("drawtext") ? "RECOMMEND_DRAWTEXT"
            : Passed("libass") ? "RECOMMEND_LIBASS"
            : "NO_COMPATIBLE_TEXT_OVERLAY_PATH_PROVEN";
    }

    private static async Task<FfmpegCapabilities> DetectCapabilitiesAsync(string root, TimeSpan timeout)
    {
        var none = new FfmpegCapabilities(null, false, false, false, false, false, false);
        var version = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffmpeg, ["-hide_banner", "-version"], root, timeout, CancellationToken.None).ConfigureAwait(false);
        if (version.StartFailed || version.ExitCode != 0)
        {
            return none;
        }
        var versionText = Encoding.UTF8.GetString(version.Stdout);
        var firstLine = versionText.Split('\n', 2)[0].Trim();
        var filters = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffmpeg, ["-hide_banner", "-filters"], root, timeout, CancellationToken.None).ConfigureAwait(false);
        var filterText = Encoding.UTF8.GetString(filters.Stdout);
        var encoders = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffmpeg, ["-hide_banner", "-encoders"], root, timeout, CancellationToken.None).ConfigureAwait(false);
        var encoderText = Encoding.UTF8.GetString(encoders.Stdout);
        var ffprobe = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffprobe, ["-hide_banner", "-version"], root, timeout, CancellationToken.None).ConfigureAwait(false);

        return new FfmpegCapabilities(
            firstLine.Length > 200 ? firstLine[..200] : firstLine,
            HasToken(filterText, "drawtext"),
            HasToken(filterText, "subtitles"),
            versionText.Contains("--enable-libass", StringComparison.Ordinal) || HasToken(filterText, "ass"),
            versionText.Contains("--enable-libfreetype", StringComparison.Ordinal) || HasToken(filterText, "drawtext"),
            Regex.IsMatch(encoderText, @"^\s*V\S*\s+libx264\s", RegexOptions.Multiline),
            !ffprobe.StartFailed && ffprobe.ExitCode == 0);
    }

    private static bool HasToken(string text, string filter) =>
        Regex.IsMatch(text, $@"^\s*\S+\s+{Regex.Escape(filter)}\s", RegexOptions.Multiline);

    private static int SelfTest()
    {
        var latin = SfntCmap.BuildFormat12Fixture((0x20, 0x7E));
        var cjk = SfntCmap.BuildFormat12Fixture((0x20, 0x7E), (0x3000, 0x9FFF), (0xFF00, 0xFFEF));
        var cmapLatinCoversEnglish = SfntCmap.TryCovers(latin, Profile.EnglishText, out var a) && a;
        var cmapLatinRejectsChinese = SfntCmap.TryCovers(latin, Profile.ChineseText, out var b) && !b;
        var cmapCjkCoversChinese = SfntCmap.TryCovers(cjk, Profile.ChineseText + Profile.ChineseAltText, out var c) && c;

        var raw = FrameAnalyzer.BuildFixture(100, Profile.Width, Profile.AnalysisRegionHeight, 25, 75);
        var analysis = FrameAnalyzer.Analyze(raw, Profile.Width, Profile.AnalysisRegionHeight, Profile.AnalysisRegionTop, 50);
        var analyzerOk = analysis is { FrameCount: 100, FirstInkFrame: 25, LastInkFrame: 75, InkFrames: 51 }
            && analysis.MidCueInkBox == new BoundingBox(100, Profile.AnalysisRegionTop + 20, 299, Profile.AnalysisRegionTop + 39);

        var filterOk = OverlayCommands.DrawtextFilter("font_en.ttf", "en.txt").Contains("between(t,1,3)", StringComparison.Ordinal);
        var unsafeDenied = false;
        try
        {
            OverlayCommands.Safe("C:\\Windows\\Fonts\\arial.ttf");
        }
        catch (InvalidOperationException)
        {
            unsafeDenied = true;
        }
        var assOk = OverlayCommands.BuildAss("Microsoft YaHei", Profile.ChineseText)
            .Contains("Dialogue: 0,0:00:01.00,0:00:03.00", StringComparison.Ordinal);

        var ok = cmapLatinCoversEnglish && cmapLatinRejectsChinese && cmapCjkCoversChinese
            && analyzerOk && filterOk && unsafeDenied && assOk;
        Console.WriteLine(JsonSerializer.Serialize(
            new
            {
                probe = "picotoopet.text_overlay_compatibility.s004.self_test",
                cmap_latin_covers_english = cmapLatinCoversEnglish,
                cmap_latin_rejects_chinese = cmapLatinRejectsChinese,
                cmap_cjk_covers_chinese = cmapCjkCoversChinese,
                frame_analyzer_timing_and_bbox = analyzerOk,
                drawtext_filter_has_cue_window = filterOk,
                unsafe_names_denied = unsafeDenied,
                ass_cue_window = assOk,
                status = ok ? Status.Pass : Status.Fail,
            },
            ProbeJson.Options));
        return ok ? 0 : 1;
    }

    private static bool TryParse(
        string[] args,
        out string selection,
        out int timeoutSeconds,
        out bool simulateNoFont,
        out bool selfTest)
    {
        selection = "all";
        timeoutSeconds = DefaultTimeoutSeconds;
        simulateNoFont = false;
        selfTest = false;
        for (var index = 0; index < args.Length; index++)
        {
            switch (args[index])
            {
                case "--path" when index + 1 < args.Length:
                    selection = args[++index];
                    if (selection is not ("all" or "drawtext" or "libass"))
                    {
                        return false;
                    }
                    break;
                case "--timeout-seconds" when index + 1 < args.Length:
                    if (!int.TryParse(args[++index], out timeoutSeconds)
                        || timeoutSeconds is < MinTimeoutSeconds or > MaxTimeoutSeconds)
                    {
                        return false;
                    }
                    break;
                case "--simulate-no-font":
                    simulateNoFont = true;
                    break;
                case "--self-test":
                    selfTest = true;
                    break;
                default:
                    return false;
            }
        }
        return true;
    }
}
