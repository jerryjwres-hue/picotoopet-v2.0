using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace PicotooPet.PostProductionAudioMuxProbe;

/// <summary>Runs the whole S005 proof inside a probe-managed directory.</summary>
internal sealed partial class MuxProbe
{
    private const string VideoFile = "input.mp4";
    private const string FinalName = "mastered.mp4";
    private const int LongTimelineMs = 7_200_000;

    private readonly string _root;
    private readonly TimeSpan _timeout;

    [GeneratedRegex("MD5=([0-9a-f]{32})")]
    private static partial Regex Md5Pattern();

    public MuxProbe(string root, TimeSpan timeout)
    {
        _root = root;
        _timeout = timeout;
    }

    // (placement, tone duration ms, sample rate, channels, frequency)
    private static readonly (NarrationPlacement Placement, int DurationMs, int Rate, int Channels, int Hz)[] Fixtures =
    [
        (new("seg1", 0, 2500, "seg1.wav"), 2000, 24000, 1, 440),
        (new("seg2", 2500, 5000, "seg2.wav"), 1500, 44100, 2, 660),
        (new("seg3", 5000, 8000, "seg3.wav"), 2500, 48000, 1, 880),
    ];

    public async Task<ProbeReport> RunAsync(CancellationToken cancellationToken)
    {
        var os = Environment.OSVersion.VersionString;
        var version = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffmpeg, ["-hide_banner", "-version"], _root, _timeout, cancellationToken).ConfigureAwait(false);
        if (version.StartFailed || version.ExitCode != 0)
        {
            return Failed(os, null, false, false, Status.FfmpegUnavailable);
        }
        var ffmpegVersion = Encoding.UTF8.GetString(version.Stdout).Split('\n', 2)[0].Trim();
        var encoders = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffmpeg, ["-hide_banner", "-encoders"], _root, _timeout, cancellationToken).ConfigureAwait(false);
        var aac = Regex.IsMatch(Encoding.UTF8.GetString(encoders.Stdout), @"^\s*A\S*\s+aac\s", RegexOptions.Multiline);
        var ffprobe = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffprobe, ["-hide_banner", "-version"], _root, _timeout, cancellationToken).ConfigureAwait(false);
        var ffprobeAvailable = !ffprobe.StartFailed && ffprobe.ExitCode == 0;
        if (!aac)
        {
            return Failed(os, ffmpegVersion, false, ffprobeAvailable, Status.AacEncoderMissing);
        }
        if (!ffprobeAvailable)
        {
            return Failed(os, ffmpegVersion, true, false, Status.FfmpegUnavailable);
        }

        // ── Synthetic inputs: H.264/yuv420p video + three WAV segments (different rates/channels). ──
        var generate = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffmpeg, MuxCommands.GenerateVideoArguments(VideoFile), _root, _timeout, cancellationToken)
            .ConfigureAwait(false);
        if (generate.ExitCode != 0)
        {
            return Failed(os, ffmpegVersion, true, true, Status.MuxFailed);
        }
        var wavReports = new List<WavReport>();
        var parsed = new List<(NarrationPlacement Placement, WavFacts? Wav)>();
        foreach (var fixture in Fixtures)
        {
            var bytes = WavFile.Build(fixture.Rate, fixture.Channels, fixture.DurationMs, fixture.Hz);
            await File.WriteAllBytesAsync(Path.Combine(_root, fixture.Placement.WavFile), bytes, cancellationToken)
                .ConfigureAwait(false);
            WavFile.TryParse(bytes, out var facts);
            parsed.Add((fixture.Placement, facts));
            wavReports.Add(new WavReport(
                fixture.Placement.Label, fixture.Rate, fixture.Channels, facts?.DurationMs ?? -1,
                fixture.Placement.StartMs, fixture.Placement.WindowEndMs));
        }
        var inputVideo = (await ProbeAsync(VideoFile, cancellationToken).ConfigureAwait(false)).Video;

        // ── Validation, then the one fixed mux command; output is promoted only on success. ──
        var validation = SegmentValidator.Validate(parsed, Profile.TimelineMs);
        var placements = Fixtures.Select(item => item.Placement).ToList();
        const string commandShapeOutput = "command-shape.partial.mp4";
        var commandShape = string.Join(
            ' ',
            MuxCommands.MuxArguments(
                VideoFile,
                placements,
                Profile.TimelineMs,
                commandShapeOutput,
                false)
            .Select(argument => argument.StartsWith("[1:a]", StringComparison.Ordinal)
                ? "<filter_complex>"
                : string.Equals(argument, commandShapeOutput, StringComparison.Ordinal)
                    ? "<partial>"
                    : argument));
        FinalStreamFacts? final = null;
        string? inputMd5 = null;
        string? finalMd5 = null;
        var copyProven = false;
        var durationOk = false;
        IReadOnlyList<WindowCheck> timeline = [];
        var muxStatus = validation ?? Status.Pass;

        var partial = "mastered.partial.mp4";
        var finalPath = Path.Combine(_root, FinalName);
        if (validation is null)
        {
            var mux = await FfmpegRunner.RunAsync(
                FfmpegRunner.Ffmpeg,
                MuxCommands.MuxArguments(VideoFile, placements, Profile.TimelineMs, partial, false),
                _root, _timeout, cancellationToken).ConfigureAwait(false);
            var partialPath = Path.Combine(_root, partial);
            if (mux.ExitCode != 0 || !File.Exists(partialPath))
            {
                muxStatus = mux.TimedOut ? Status.Timeout : Status.MuxFailed;
            }
            else
            {
                File.Move(partialPath, finalPath, overwrite: false);
                var probe = await ProbeAsync(FinalName, cancellationToken).ConfigureAwait(false);
                final = probe with { Bytes = new FileInfo(finalPath).Length };
                inputMd5 = await VideoPacketMd5Async(VideoFile, cancellationToken).ConfigureAwait(false);
                finalMd5 = await VideoPacketMd5Async(FinalName, cancellationToken).ConfigureAwait(false);
                copyProven = inputMd5 is not null && inputMd5 == finalMd5
                    && final.Video is { } video && inputVideo is { } source
                    && video.Codec == "h264" && video == source;
                durationOk = Math.Abs(final.DurationSeconds - (Profile.TimelineMs / 1000.0)) <= Profile.DurationToleranceSeconds;
                var decode = await FfmpegRunner.RunAsync(
                    FfmpegRunner.Ffmpeg, MuxCommands.DecodeAudioArguments(FinalName), _root, _timeout, cancellationToken)
                    .ConfigureAwait(false);
                timeline = AudioAnalyzer.CheckTimeline(
                    decode.Stdout,
                    Fixtures.Select(item => (item.Placement, item.DurationMs, item.Hz)).ToList(),
                    Profile.TimelineMs);
            }
        }

        var streamsOk = final is { VideoStreams: 1, AudioStreams: 1, OtherStreams: 0 }
            && final.Audio is { Codec: "aac", Profile: "LC", SampleRate: Profile.AudioRate, Channels: 1 };
        var passed = muxStatus == Status.Pass && streamsOk && copyProven && durationOk
            && timeline.Count > 0 && timeline.All(check => check.Ok);

        var negative = await RunOverlongNegativeAsync(cancellationToken).ConfigureAwait(false);
        var cancellation = await BoundedAsync(cancel: true, cancellationToken).ConfigureAwait(false);
        var timeout = await BoundedAsync(cancel: false, cancellationToken).ConfigureAwait(false);
        var noPartial = !File.Exists(Path.Combine(_root, "stress-cancel.partial.mp4"))
            && !File.Exists(Path.Combine(_root, "stress-timeout.partial.mp4"))
            && !File.Exists(Path.Combine(_root, "negative.mp4"))
            && !File.Exists(Path.Combine(_root, "failure.mp4"));
        var failureLeavesNoOutput = await FailureLeavesNoOutputAsync(cancellationToken).ConfigureAwait(false) && noPartial;

        var overall = passed && negative.Rejected && cancellation.Bounded && timeout.Bounded && failureLeavesNoOutput;
        return new ProbeReport(
            "picotoopet.postproduction_audio_mux.s005",
            os,
            ffmpegVersion,
            aac,
            ffprobeAvailable,
            inputVideo,
            wavReports,
            commandShape,
            final,
            copyProven,
            inputMd5,
            finalMd5,
            durationOk,
            timeline,
            cancellation,
            timeout,
            negative,
            failureLeavesNoOutput,
            overall ? Status.Pass : (muxStatus != Status.Pass ? muxStatus : Status.Fail),
            overall ? "RECOMMEND_STREAM_COPY_AAC_MUX" : "NO_COMPATIBLE_AUDIO_MUX_PATH_PROVEN");
    }

    /// <summary>Negative control: a WAV longer than its window must be rejected before ffmpeg is invoked.</summary>
    private async Task<NegativeCheck> RunOverlongNegativeAsync(CancellationToken cancellationToken)
    {
        var placement = new NarrationPlacement("overlong", 0, 2000, "overlong.wav");
        var bytes = WavFile.Build(48000, 1, 3000, 440);
        await File.WriteAllBytesAsync(Path.Combine(_root, placement.WavFile), bytes, cancellationToken)
            .ConfigureAwait(false);
        WavFile.TryParse(bytes, out var facts);
        var verdict = SegmentValidator.Validate([(placement, facts)], Profile.TimelineMs);
        var invoked = false;
        if (verdict is null)
        {
            // Would have been muxed: record that the guard failed to stop it.
            invoked = true;
            await FfmpegRunner.RunAsync(
                FfmpegRunner.Ffmpeg,
                MuxCommands.MuxArguments(VideoFile, [placement], Profile.TimelineMs, "negative.mp4", false),
                _root, _timeout, cancellationToken).ConfigureAwait(false);
        }
        var exists = File.Exists(Path.Combine(_root, "negative.mp4"));
        return new NegativeCheck(verdict ?? Status.Pass, invoked, exists, verdict == Status.SegmentTooLong && !invoked && !exists);
    }

    /// <summary>A failing mux (missing audio input) must leave no durable final output.</summary>
    private async Task<bool> FailureLeavesNoOutputAsync(CancellationToken cancellationToken)
    {
        var missing = new NarrationPlacement("missing", 0, 2000, "does-not-exist.wav");
        var result = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffmpeg,
            MuxCommands.MuxArguments(VideoFile, [missing], Profile.TimelineMs, "failure.partial.mp4", false),
            _root, _timeout, cancellationToken).ConfigureAwait(false);
        var partial = Path.Combine(_root, "failure.partial.mp4");
        if (File.Exists(partial))
        {
            File.Delete(partial); // the product promotes only on success; leftovers live in the managed work dir
        }
        return result.ExitCode != 0 && !File.Exists(Path.Combine(_root, "failure.mp4"));
    }

    /// <summary>Very long loop-copy + AAC encode of the real command shape; cancel/timeout must bound it.</summary>
    private async Task<BoundedCheck> BoundedAsync(bool cancel, CancellationToken cancellationToken)
    {
        var placements = Fixtures.Select(item => item.Placement).ToList();
        var output = cancel ? "stress-cancel.partial.mp4" : "stress-timeout.partial.mp4";
        using var source = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        if (cancel)
        {
            source.CancelAfter(TimeSpan.FromMilliseconds(300));
        }
        var clock = System.Diagnostics.Stopwatch.StartNew();
        var outcome = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffmpeg,
            MuxCommands.MuxArguments(VideoFile, placements, LongTimelineMs, output, stress: true),
            _root,
            cancel ? TimeSpan.FromMinutes(10) : TimeSpan.FromSeconds(1),
            source.Token).ConfigureAwait(false);
        var elapsed = clock.ElapsedMilliseconds;
        var path = Path.Combine(_root, output);
        if (File.Exists(path))
        {
            File.Delete(path);
        }
        var status = outcome.Unresponsive ? Status.Unresponsive
            : outcome.Cancelled ? Status.Cancelled
            : outcome.TimedOut ? Status.Timeout
            : Status.NotRun;
        return new BoundedCheck(status, elapsed, status == (cancel ? Status.Cancelled : Status.Timeout) && elapsed <= 8000);
    }

    private async Task<string?> VideoPacketMd5Async(string file, CancellationToken cancellationToken)
    {
        var result = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffmpeg, MuxCommands.VideoPacketMd5Arguments(file), _root, _timeout, cancellationToken)
            .ConfigureAwait(false);
        var match = Md5Pattern().Match(Encoding.UTF8.GetString(result.Stdout));
        return result.ExitCode == 0 && match.Success ? match.Groups[1].Value : null;
    }

    private async Task<FinalStreamFacts> ProbeAsync(string file, CancellationToken cancellationToken)
    {
        var result = await FfmpegRunner.RunAsync(
            FfmpegRunner.Ffprobe, MuxCommands.ProbeArguments(file), _root, _timeout, cancellationToken)
            .ConfigureAwait(false);
        var empty = new FinalStreamFacts(0, 0, 0, null, null, 0, 0);
        if (result.ExitCode != 0)
        {
            return empty;
        }
        try
        {
            using var document = JsonDocument.Parse(result.Stdout);
            VideoFacts? video = null;
            AudioFacts? audio = null;
            int videos = 0, audios = 0, others = 0;
            foreach (var stream in document.RootElement.GetProperty("streams").EnumerateArray())
            {
                switch (stream.GetProperty("codec_type").GetString())
                {
                    case "video":
                        videos++;
                        video = new VideoFacts(
                            stream.GetProperty("codec_name").GetString() ?? string.Empty,
                            stream.GetProperty("width").GetInt32(),
                            stream.GetProperty("height").GetInt32(),
                            stream.GetProperty("r_frame_rate").GetString() ?? string.Empty,
                            stream.GetProperty("pix_fmt").GetString() ?? string.Empty,
                            int.Parse(stream.GetProperty("nb_read_packets").GetString() ?? "0"));
                        break;
                    case "audio":
                        audios++;
                        audio = new AudioFacts(
                            stream.GetProperty("codec_name").GetString() ?? string.Empty,
                            stream.TryGetProperty("profile", out var profile) ? profile.GetString() ?? string.Empty : string.Empty,
                            int.Parse(stream.GetProperty("sample_rate").GetString() ?? "0"),
                            stream.GetProperty("channels").GetInt32());
                        break;
                    default:
                        others++;
                        break;
                }
            }
            var duration = double.Parse(
                document.RootElement.GetProperty("format").GetProperty("duration").GetString() ?? "0",
                System.Globalization.CultureInfo.InvariantCulture);
            return new FinalStreamFacts(videos, audios, others, video, audio, duration, 0);
        }
        catch (Exception exception) when (exception is JsonException or KeyNotFoundException or FormatException
            or InvalidOperationException)
        {
            return empty;
        }
    }

    private static ProbeReport Failed(string os, string? version, bool aac, bool ffprobe, string status) =>
        new(
            "picotoopet.postproduction_audio_mux.s005", os, version, aac, ffprobe, null, [], string.Empty, null,
            false, null, null, false, [], null, null, null, false, status, "NO_COMPATIBLE_AUDIO_MUX_PATH_PROVEN");
}
