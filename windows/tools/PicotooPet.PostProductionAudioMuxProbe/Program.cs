using System.Text.Json;

namespace PicotooPet.PostProductionAudioMuxProbe;

/// <summary>
/// S005 compatibility probe. Closed argument set; no filter, path, codec, font or executable input exists.
/// Writes only under a probe-managed temp directory that is always removed.
/// </summary>
internal static class Program
{
    private const int MinTimeoutSeconds = 5;
    private const int MaxTimeoutSeconds = 120;
    private const int DefaultTimeoutSeconds = 60;

    public static async Task<int> Main(string[] args)
    {
        if (!TryParse(args, out var timeoutSeconds, out var selfTest))
        {
            Console.Error.WriteLine("INVALID_ARGUMENT usage: [--timeout-seconds 5..120] [--self-test]");
            return 3;
        }
        if (selfTest)
        {
            return SelfTest();
        }
        if (!OperatingSystem.IsWindows())
        {
            Console.WriteLine(JsonSerializer.Serialize(
                new { probe = "picotoopet.postproduction_audio_mux.s005", status = Status.NotWindows },
                ProbeJson.Options));
            return 1;
        }

        var root = Path.Combine(Path.GetTempPath(), "PicotooPetAudioMuxProbe", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var report = await new MuxProbe(root, TimeSpan.FromSeconds(timeoutSeconds))
                .RunAsync(CancellationToken.None).ConfigureAwait(false);
            Console.WriteLine(JsonSerializer.Serialize(report, ProbeJson.Options));
            return report.Status == Status.Pass ? 0 : 1;
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

    private static int SelfTest()
    {
        var wav = WavFile.Build(24000, 1, 2000, 440);
        var wavOk = WavFile.TryParse(wav, out var facts) && facts is { Channels: 1, SampleRate: 24000, DurationMs: 2000 };
        var stereoOk = WavFile.TryParse(WavFile.Build(44100, 2, 1500, 660), out var stereo)
            && stereo is { Channels: 2, SampleRate: 44100, DurationMs: 1500 };
        var badWav = !WavFile.TryParse(new byte[10], out _);

        // 48 kHz mono s16le fixture: 440 Hz at 1000–2000 ms, silence elsewhere.
        var pcm = new byte[Profile.AudioRate * 2 * 3];
        for (var index = Profile.AudioRate; index < Profile.AudioRate * 2; index++)
        {
            var sample = (short)(0.5 * short.MaxValue * Math.Sin(2 * Math.PI * 440 * index / Profile.AudioRate));
            BitConverter.TryWriteBytes(pcm.AsSpan(index * 2, 2), sample);
        }
        var toneRms = AudioAnalyzer.Rms(pcm, 1200, 1800);
        var silenceRms = AudioAnalyzer.Rms(pcm, 100, 800);
        var toneHz = AudioAnalyzer.StrongestTone(pcm, 1200, 1800);
        var silentHz = AudioAnalyzer.StrongestTone(pcm, 100, 800);
        var analyzerOk = toneRms > 10000 && silenceRms < 1 && toneHz == 440 && silentHz == 0;

        var placements = new List<NarrationPlacement> { new("a", 0, 2500, "a.wav"), new("b", 2500, 5000, "b.wav") };
        var filter = MuxCommands.FilterComplex(placements, 8000);
        var filterOk = filter.Contains("adelay=2500:all=1", StringComparison.Ordinal)
            && filter.Contains("amix=inputs=2:duration=longest:normalize=0", StringComparison.Ordinal)
            && filter.Contains("apad=whole_dur=8.000", StringComparison.Ordinal)
            && !filter.Contains("atempo", StringComparison.Ordinal)
            && !filter.Contains("atrim", StringComparison.Ordinal);
        var args = MuxCommands.MuxArguments("input.mp4", placements, 8000, "out.mp4", false);
        var argsOk = args.Contains("copy") && args.Contains("aac_low") && args.Contains("+faststart")
            && !args.Contains("libx264") && !args.Contains("-shortest");

        var tooLong = SegmentValidator.Validate(
            [(new NarrationPlacement("x", 0, 2000, "x.wav"), new WavFacts(1, 48000, 16, 0, 3000))], 8000)
            == Status.SegmentTooLong;
        var outside = SegmentValidator.Validate(
            [(new NarrationPlacement("x", 7000, 8500, "x.wav"), new WavFacts(1, 48000, 16, 0, 1000))], 8000)
            == Status.SegmentOutsideTimeline;
        var overlap = SegmentValidator.Validate(
            [
                (new NarrationPlacement("a", 0, 3000, "a.wav"), new WavFacts(1, 48000, 16, 0, 1000)),
                (new NarrationPlacement("b", 2000, 4000, "b.wav"), new WavFacts(1, 48000, 16, 0, 1000)),
            ], 8000) == Status.SegmentOverlap;
        var accepts = SegmentValidator.Validate(
            [(new NarrationPlacement("x", 0, 2500, "x.wav"), new WavFacts(1, 48000, 16, 0, 2000))], 8000) is null;

        var unsafeDenied = false;
        try
        {
            MuxCommands.Safe("C:\\evil.wav");
        }
        catch (InvalidOperationException)
        {
            unsafeDenied = true;
        }

        var ok = wavOk && stereoOk && badWav && analyzerOk && filterOk && argsOk
            && tooLong && outside && overlap && accepts && unsafeDenied;
        Console.WriteLine(JsonSerializer.Serialize(
            new
            {
                probe = "picotoopet.postproduction_audio_mux.s005.self_test",
                wav_roundtrip = wavOk && stereoOk,
                wav_rejects_garbage = badWav,
                analyzer_rms_and_tone = analyzerOk,
                filter_has_delay_mix_pad_and_no_trim_or_tempo = filterOk,
                args_stream_copy_aac_lc_faststart = argsOk,
                overlong_rejected = tooLong,
                outside_timeline_rejected = outside,
                overlap_rejected = overlap,
                valid_segment_accepted = accepts,
                unsafe_names_denied = unsafeDenied,
                status = ok ? Status.Pass : Status.Fail,
            },
            ProbeJson.Options));
        return ok ? 0 : 1;
    }

    private static bool TryParse(string[] args, out int timeoutSeconds, out bool selfTest)
    {
        timeoutSeconds = DefaultTimeoutSeconds;
        selfTest = false;
        for (var index = 0; index < args.Length; index++)
        {
            switch (args[index])
            {
                case "--timeout-seconds" when index + 1 < args.Length:
                    if (!int.TryParse(args[++index], out timeoutSeconds)
                        || timeoutSeconds is < MinTimeoutSeconds or > MaxTimeoutSeconds)
                    {
                        return false;
                    }
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
