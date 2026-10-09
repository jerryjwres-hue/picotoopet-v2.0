using System.Globalization;
using System.Text.RegularExpressions;

namespace PicotooPet.PostProductionAudioMuxProbe;

/// <summary>
/// Builds the only commands this probe can run. All inputs are probe-authored relative file names in a
/// managed working directory; the single filter_complex is generated from integer start_ms values.
/// </summary>
internal static partial class MuxCommands
{
    [GeneratedRegex("^[A-Za-z0-9_.-]+$")]
    private static partial Regex SafeName();

    public static string Safe(string name) =>
        SafeName().IsMatch(name) ? name : throw new InvalidOperationException("UNSAFE_NAME_DENIED");

    private static string Invariant(int value) => value.ToString(CultureInfo.InvariantCulture);

    private static string Seconds(int milliseconds) =>
        string.Create(CultureInfo.InvariantCulture, $"{milliseconds / 1000}.{milliseconds % 1000:D3}");

    /// <summary>
    /// Normalize every segment to mono 48 kHz float, delay it to its start_ms, sum non-overlapping
    /// segments without gain change, and pad with silence to the exact video timeline. Never trims,
    /// speeds up or resamples time; overlong inputs are rejected before this graph exists.
    /// </summary>
    public static string FilterComplex(IReadOnlyList<NarrationPlacement> placements, int timelineMs)
    {
        var parts = new List<string>();
        for (var index = 0; index < placements.Count; index++)
        {
            parts.Add(
                $"[{index + 1}:a]aformat=sample_rates={Invariant(Profile.AudioRate)}:channel_layouts=mono:sample_fmts=fltp,"
                + $"adelay={Invariant(placements[index].StartMs)}:all=1[a{index}]");
        }
        var inputs = string.Concat(Enumerable.Range(0, placements.Count).Select(index => $"[a{index}]"));
        parts.Add(
            $"{inputs}amix=inputs={Invariant(placements.Count)}:duration=longest:normalize=0,"
            + $"apad=whole_dur={Seconds(timelineMs)}[aout]");
        return string.Join(';', parts);
    }

    /// <param name="stress">Bounded-process control only: loops the video input and extends the timeline.</param>
    public static IReadOnlyList<string> MuxArguments(
        string videoFile,
        IReadOnlyList<NarrationPlacement> placements,
        int timelineMs,
        string outputFile,
        bool stress)
    {
        var arguments = new List<string> { "-hide_banner", "-loglevel", "error", "-nostdin", "-y" };
        if (stress)
        {
            arguments.AddRange(["-stream_loop", "-1"]);
        }
        arguments.AddRange(["-i", Safe(videoFile)]);
        foreach (var placement in placements)
        {
            arguments.AddRange(["-i", Safe(placement.WavFile)]);
        }
        arguments.AddRange(
        [
            "-filter_complex", FilterComplex(placements, timelineMs),
            "-map", "0:v:0", "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k", "-ar", Invariant(Profile.AudioRate), "-ac", "1",
            "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact",
            "-movflags", "+faststart",
        ]);
        if (stress)
        {
            arguments.AddRange(["-t", Seconds(timelineMs)]);
        }
        arguments.AddRange(["-f", "mp4", Safe(outputFile)]);
        return arguments;
    }

    public static IReadOnlyList<string> GenerateVideoArguments(string outputFile) =>
    [
        "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "lavfi", "-i", $"testsrc2=s={Invariant(Profile.Width)}x{Invariant(Profile.Height)}:r={Invariant(Profile.Fps)}:d={Seconds(Profile.TimelineMs)}",
        "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-x264-params", "keyint=25",
        "-f", "mp4", Safe(outputFile),
    ];

    public static IReadOnlyList<string> VideoPacketMd5Arguments(string file) =>
        ["-hide_banner", "-loglevel", "error", "-nostdin", "-i", Safe(file), "-map", "0:v:0", "-c", "copy", "-f", "md5", "-"];

    public static IReadOnlyList<string> DecodeAudioArguments(string file) =>
    [
        "-hide_banner", "-loglevel", "error", "-nostdin", "-i", Safe(file),
        "-map", "0:a:0", "-f", "s16le", "-ac", "1", "-ar", Invariant(Profile.AudioRate), "pipe:1",
    ];

    public static IReadOnlyList<string> ProbeArguments(string file) =>
    [
        "-v", "error", "-count_packets",
        "-show_entries",
        "stream=codec_type,codec_name,profile,width,height,r_frame_rate,pix_fmt,sample_rate,channels,nb_read_packets:format=duration",
        "-of", "json", Safe(file),
    ];
}
