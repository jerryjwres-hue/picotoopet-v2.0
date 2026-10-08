using System.Text;

namespace PicotooPet.TextOverlayCompatibilityProbe;

internal sealed record FfmpegCapabilities(
    string? Version,
    bool Drawtext,
    bool Subtitles,
    bool Libass,
    bool Libfreetype,
    bool X264,
    bool FfprobeAvailable);

/// <summary>Evaluates one overlay path end to end inside a probe-managed working directory.</summary>
internal sealed class PathEvaluator
{
    private readonly string _root;
    private readonly FfmpegCapabilities _capabilities;
    private readonly TimeSpan _timeout;
    private readonly bool _simulateNoFont;

    public PathEvaluator(string root, FfmpegCapabilities capabilities, TimeSpan timeout, bool simulateNoFont)
    {
        _root = root;
        _capabilities = capabilities;
        _timeout = timeout;
        _simulateNoFont = simulateNoFont;
    }

    public async Task<PathReport> EvaluateAsync(OverlayPath path)
    {
        var name = path == OverlayPath.Drawtext ? "drawtext" : "libass";
        var filterPresent = path == OverlayPath.Drawtext
            ? _capabilities.Drawtext && _capabilities.Libfreetype
            : _capabilities.Subtitles && _capabilities.Libass;
        if (!_capabilities.X264)
        {
            return Empty(name, Status.EncoderMissing, filterPresent);
        }
        if (!filterPresent)
        {
            return Empty(name, Status.FilterMissing, filterPresent);
        }

        var (zhFont, zhStatus) = FontPolicy.Resolve(
            FontPolicy.ChineseCandidates, Profile.ChineseText + Profile.ChineseAltText, _simulateNoFont);
        var (enFont, enStatus) = FontPolicy.Resolve(
            FontPolicy.EnglishCandidates, Profile.EnglishText, _simulateNoFont);
        if (zhFont is null || enFont is null)
        {
            var failure = zhFont is null ? zhStatus : enStatus;
            return Empty(name, failure, filterPresent) with
            {
                EnglishFont = enFont?.Candidate.FileName,
                ChineseFont = zhFont?.Candidate.FileName,
            };
        }

        var directory = Path.Combine(_root, name);
        Directory.CreateDirectory(directory);
        Stage(directory, "en", enFont, Profile.EnglishText);
        Stage(directory, "zh", zhFont, Profile.ChineseText);
        Stage(directory, "zh_alt", zhFont, Profile.ChineseAltText);

        var renders = new List<RenderCheck>();
        var analyses = new Dictionary<string, FrameAnalysis?>();
        foreach (var (label, check) in new[] { ("en", true), ("zh", true), ("zh_alt", false), ("zh_again", false) })
        {
            var stageLabel = label == "zh_again" ? "zh" : label;
            var (render, analysis) = await RenderAndCheckAsync(path, directory, label, stageLabel, check)
                .ConfigureAwait(false);
            analyses[label] = analysis;
            if (check || render.Status != Status.Pass)
            {
                renders.Add(render);
            }
        }

        var deterministic = analyses["zh"] is { } first && analyses["zh_again"] is { } again
            && first.RawSha256 == again.RawSha256;
        var distinct = analyses["zh"] is { } zh && analyses["zh_alt"] is { } alt
            && zh.RawSha256 != alt.RawSha256;

        var cancellation = await RunBoundedAsync(directory, path, cancel: true).ConfigureAwait(false);
        var timeout = await RunBoundedAsync(directory, path, cancel: false).ConfigureAwait(false);

        var status = renders.FirstOrDefault(render => render.Status != Status.Pass)?.Status
            ?? (!deterministic ? Status.NotDeterministic
                : !distinct ? Status.GlyphNotDistinct
                : !cancellation.Bounded || !timeout.Bounded ? Status.Unresponsive
                : Status.Pass);
        return new PathReport(
            name,
            status,
            filterPresent,
            enFont.Candidate.FileName,
            zhFont.Candidate.FileName,
            renders,
            deterministic,
            distinct,
            cancellation,
            timeout);
    }

    private static PathReport Empty(string name, string status, bool filterPresent) =>
        new(name, status, filterPresent, null, null, [], false, false, null, null);

    /// <summary>Copies the chosen system font into the managed directory and writes the fixed cue assets.</summary>
    private static void Stage(string directory, string label, ResolvedFont font, string text)
    {
        var extension = Path.GetExtension(font.Candidate.FileName);
        File.WriteAllBytes(Path.Combine(directory, $"font_{label}{extension}"), font.Bytes);
        var fontsDirectory = Path.Combine(directory, $"fonts_{label}");
        Directory.CreateDirectory(fontsDirectory);
        File.WriteAllBytes(Path.Combine(fontsDirectory, font.Candidate.FileName), font.Bytes);
        File.WriteAllText(Path.Combine(directory, $"{label}.txt"), text, new UTF8Encoding(false));
        File.WriteAllText(
            Path.Combine(directory, $"{label}.ass"),
            OverlayCommands.BuildAss(font.Candidate.Family, text),
            new UTF8Encoding(false));
    }

    private string FilterFor(OverlayPath path, string directory, string stageLabel)
    {
        if (path == OverlayPath.Libass)
        {
            return OverlayCommands.LibassFilter($"{stageLabel}.ass", $"fonts_{stageLabel}");
        }
        var fontFile = Directory.GetFiles(directory, $"font_{stageLabel}.*").Select(Path.GetFileName).First()!;
        return OverlayCommands.DrawtextFilter(fontFile, $"{stageLabel}.txt");
    }

    private async Task<(RenderCheck Render, FrameAnalysis? Analysis)> RenderAndCheckAsync(
        OverlayPath path,
        string directory,
        string label,
        string stageLabel,
        bool strictChecks)
    {
        var output = $"out_{label}.mp4";
        var outputPath = Path.Combine(directory, output);
        var render = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffmpeg,
            OverlayCommands.RenderArguments(Profile.DurationSeconds, FilterFor(path, directory, stageLabel), output),
            directory,
            _timeout,
            CancellationToken.None).ConfigureAwait(false);
        if (render.TimedOut || render.Unresponsive || render.StartFailed || render.ExitCode != 0)
        {
            var code = render.TimedOut ? Status.Timeout : render.Unresponsive ? Status.Unresponsive : Status.RenderFailed;
            return (Fail(label, code), null);
        }

        var bytes = File.Exists(outputPath) ? new FileInfo(outputPath).Length : 0;
        var decode = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffmpeg, OverlayCommands.DecodeCheckArguments(output), directory, _timeout, CancellationToken.None)
            .ConfigureAwait(false);
        string? codec = null;
        int probedWidth = 0, probedHeight = 0;
        var probed = false;
        if (_capabilities.FfprobeAvailable)
        {
            var probe = await FfmpegRunner.RunAsync(
                FfmpegRunner.Ffprobe, OverlayCommands.ProbeArguments(output), directory, _timeout, CancellationToken.None)
                .ConfigureAwait(false);
            var parts = Encoding.UTF8.GetString(probe.Stdout).Trim().Split(',');
            if (probe.ExitCode == 0 && parts.Length >= 3
                && int.TryParse(parts[1], out probedWidth) && int.TryParse(parts[2], out probedHeight))
            {
                codec = parts[0];
                probed = true;
            }
        }
        var valid = bytes > 0 && decode.ExitCode == 0
            && (!_capabilities.FfprobeAvailable
                || (probed && codec == "h264" && probedWidth == Profile.Width && probedHeight == Profile.Height));
        if (!valid)
        {
            return (Fail(label, Status.OutputInvalid) with { OutputBytes = bytes, FfprobeReadable = probed, VideoCodec = codec }, null);
        }

        var extract = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffmpeg, OverlayCommands.ExtractArguments(output), directory, _timeout, CancellationToken.None)
            .ConfigureAwait(false);
        if (extract.ExitCode != 0 || extract.Stdout.Length == 0)
        {
            return (Fail(label, Status.OutputInvalid) with { OutputBytes = bytes }, null);
        }
        var midFrame = (Profile.CueStartSeconds + Profile.CueEndSeconds) * Profile.Fps / 2;
        var analysis = FrameAnalyzer.Analyze(
            extract.Stdout, Profile.Width, Profile.AnalysisRegionHeight, Profile.AnalysisRegionTop, midFrame);

        var cueFirst = Profile.CueStartSeconds * Profile.Fps;
        var cueLast = Profile.CueEndSeconds * Profile.Fps;
        var timingOk = analysis.FirstInkFrame is >= 0
            && Math.Abs(analysis.FirstInkFrame - cueFirst) <= 1
            && Math.Abs(analysis.LastInkFrame - cueLast) <= 1
            && analysis.InkFrames == (analysis.LastInkFrame - analysis.FirstInkFrame + 1)
            && analysis.FrameCount == Profile.DurationSeconds * Profile.Fps;
        var box = analysis.MidCueInkBox;
        var centerOffset = box is null ? int.MaxValue : Math.Abs(((box.X0 + box.X1) / 2) - (Profile.Width / 2));
        var geometryOk = box is not null
            && box.X0 >= Profile.SafeLeft && box.X1 <= Profile.SafeRight
            && box.Y0 >= Profile.SafeTop && box.Y1 <= Profile.SafeBottom
            && centerOffset <= Profile.MaxCenterOffsetPx;

        var status = !strictChecks ? Status.Pass
            : !timingOk ? Status.TimingViolation
            : !geometryOk ? Status.GeometryViolation
            : Status.Pass;
        return (
            new RenderCheck(
                label,
                status,
                bytes,
                probed,
                codec,
                probedWidth,
                probedHeight,
                analysis.FrameCount,
                analysis.FirstInkFrame,
                analysis.LastInkFrame,
                box,
                centerOffset == int.MaxValue ? -1 : centerOffset),
            analysis);
    }

    /// <summary>Starts a very long fixed render, then cancels (or lets the timeout fire) and measures the bound.</summary>
    private async Task<BoundedProcessCheck> RunBoundedAsync(
        string directory,
        OverlayPath path,
        bool cancel)
    {
        const int longDurationSeconds = 7200;
        var arguments = OverlayCommands.RenderArguments(
            longDurationSeconds, FilterFor(path, directory, "en"), cancel ? "cancel.mp4" : "timeout.mp4");
        using var source = new CancellationTokenSource();
        var bound = TimeSpan.FromSeconds(1);
        var clock = System.Diagnostics.Stopwatch.StartNew();
        if (cancel)
        {
            source.CancelAfter(TimeSpan.FromMilliseconds(300));
        }
        var outcome = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffmpeg,
            arguments,
            directory,
            cancel ? TimeSpan.FromMinutes(5) : bound,
            source.Token).ConfigureAwait(false);
        var elapsed = clock.ElapsedMilliseconds;
        var status = outcome.Unresponsive ? Status.Unresponsive
            : outcome.Cancelled ? Status.Cancelled
            : outcome.TimedOut ? Status.Timeout
            : Status.NotRun; // finished or failed before the bound; the bound was not demonstrated
        var expected = cancel ? Status.Cancelled : Status.Timeout;
        return new BoundedProcessCheck(status, elapsed, status == expected && elapsed <= 8000);
    }

    private static RenderCheck Fail(string label, string status) =>
        new(label, status, 0, false, null, 0, 0, 0, -1, -1, null, -1);
}
