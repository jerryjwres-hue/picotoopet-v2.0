using System.Diagnostics;
using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.Json;

namespace PicotooPet.Desktop.Services;

/// <summary>C010 policy uses the existing bounded process runner, never the mux acceptance policy.</summary>
public sealed class FinalVideoQaMediaProbe
{
    private readonly IMasterVideoProcessRunner _runner;
    public FinalVideoQaMediaProbe(IMasterVideoProcessRunner runner) => _runner = runner;

    internal async Task<FinalQaObservedMedia> VerifyAsync(string path, string profile, bool narration,
        long frames, long targetMs, CancellationToken ct)
    {
        var probe = Start("ffprobe.exe", path,
            ["-v", "error", "-count_packets", "-show_entries",
             "format=format_name,duration,nb_streams:stream=index,codec_type,codec_name,profile,pix_fmt,width,height,r_frame_rate,avg_frame_rate,duration,time_base,sample_rate,channels,channel_layout,nb_read_packets:stream_disposition=attached_pic:chapter=id",
             "-of", "json", path]);
        var result = await RunAsync(probe, TimeSpan.FromSeconds(30), "PROBE_FAILED", ct).ConfigureAwait(false);
        var facts = Parse(result.Stdout);
        Validate(facts, profile, narration, frames, targetMs);
        var args = new List<string> { "-hide_banner", "-loglevel", "error", "-nostdin", "-xerror", "-i", path, "-map", "0:v:0" };
        if (narration) args.AddRange(["-map", "0:a:0"]);
        args.AddRange(["-f", "null", "-"]);
        await RunAsync(Start("ffmpeg.exe", path, args), TimeSpan.FromMinutes(2), "DECODE_FAILED", ct).ConfigureAwait(false);
        return facts;
    }

    private async Task<MasterVideoProcessResult> RunAsync(ProcessStartInfo start, TimeSpan timeout, string error, CancellationToken ct)
    {
        try
        {
            var result = await _runner.RunAsync(start, timeout, ct).ConfigureAwait(false);
            if (result.TimedOut) throw new FinalVideoQaException("TIMEOUT");
            if (result.ExitCode != 0) throw new FinalVideoQaException(error);
            return result;
        }
        catch (MasterVideoComposerException) { throw new FinalVideoQaException("PROBE_UNAVAILABLE"); }
        catch (Exception e) when (e is IOException or InvalidDataException or UnauthorizedAccessException
            or System.ComponentModel.Win32Exception or InvalidOperationException or ArgumentException)
        { throw new FinalVideoQaException(error); }
    }

    private static ProcessStartInfo Start(string exe, string path, IEnumerable<string> args)
    {
        var start = new ProcessStartInfo(exe) { UseShellExecute = false, CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(path) ?? string.Empty };
        foreach (var arg in args) start.ArgumentList.Add(arg);
        return start;
    }

    public static FinalQaObservedMedia Parse(string json)
    {
        try
        {
            if (Encoding.UTF8.GetByteCount(json) is <= 0 or > 512 * 1024) throw new FinalVideoQaException("PROBE_FAILED");
            using var doc = JsonDocument.Parse(json, new JsonDocumentOptions { MaxDepth = 16 });
            var root = doc.RootElement;
            RejectDuplicates(root);
            if (root.TryGetProperty("chapters", out var chapters) && chapters.GetArrayLength() != 0)
                throw new FinalVideoQaException("UNEXPECTED_STREAM");
            var format = root.GetProperty("format");
            if (!(format.GetProperty("format_name").GetString() ?? "").Split(',').Contains("mp4", StringComparer.Ordinal))
                throw new FinalVideoQaException("CONTAINER_INVALID");
            var duration = Duration(format);
            var streams = root.GetProperty("streams").EnumerateArray().ToArray();
            if (streams.Length != format.GetProperty("nb_streams").GetInt32() || streams.Length is < 1 or > 2)
                throw new FinalVideoQaException("UNEXPECTED_STREAM");
            FinalQaVideoFacts? video = null;
            FinalQaAudioFacts? audio = null;
            foreach (var stream in streams)
            {
                if (stream.GetProperty("disposition").GetProperty("attached_pic").GetInt32() != 0)
                    throw new FinalVideoQaException("UNEXPECTED_STREAM");
                var index = stream.GetProperty("index").GetInt32();
                var codec = stream.GetProperty("codec_name").GetString()!;
                switch (stream.GetProperty("codec_type").GetString())
                {
                    case "video":
                        if (video is not null) throw new FinalVideoQaException("UNEXPECTED_STREAM");
                        var fps = Rational(stream.GetProperty("avg_frame_rate").GetString());
                        var rate = Rational(stream.GetProperty("r_frame_rate").GetString());
                        if (fps.Item1 * (BigInteger)rate.Item2 != rate.Item1 * (BigInteger)fps.Item2)
                            throw new FinalVideoQaException("OUTPUT_PROFILE_MISMATCH");
                        long? packets = stream.TryGetProperty("nb_read_packets", out var count) && count.GetString() != "N/A"
                            ? long.Parse(count.GetString()!, CultureInfo.InvariantCulture) : null;
                        video = new(index, codec, stream.GetProperty("pix_fmt").GetString()!,
                            stream.GetProperty("width").GetInt32(), stream.GetProperty("height").GetInt32(),
                            fps.Item1, fps.Item2, Duration(stream), packets);
                        break;
                    case "audio":
                        if (audio is not null) throw new FinalVideoQaException("UNEXPECTED_STREAM");
                        audio = new(index, codec, stream.GetProperty("profile").GetString()!,
                            int.Parse(stream.GetProperty("sample_rate").GetString()!, CultureInfo.InvariantCulture),
                            stream.GetProperty("channels").GetInt32(),
                            stream.TryGetProperty("channel_layout", out var layout) ? layout.GetString() : null, Duration(stream));
                        break;
                    default: throw new FinalVideoQaException("UNEXPECTED_STREAM");
                }
            }
            return new("mp4", duration, streams.Length, video ?? throw new FinalVideoQaException("VIDEO_STREAM_INVALID"), audio);
        }
        catch (FinalVideoQaException) { throw; }
        catch (Exception e) when (e is JsonException or KeyNotFoundException or InvalidOperationException
            or FormatException or OverflowException or ArgumentException)
        { throw new FinalVideoQaException("PROBE_FAILED"); }
    }

    internal static void RejectDuplicates(JsonElement node)
    {
        if (node.ValueKind == JsonValueKind.Object)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var property in node.EnumerateObject())
            {
                if (!names.Add(property.Name)) throw new JsonException();
                RejectDuplicates(property.Value);
            }
        }
        else if (node.ValueKind == JsonValueKind.Array)
            foreach (var item in node.EnumerateArray()) RejectDuplicates(item);
    }
    private static long Duration(JsonElement node)
    {
        var seconds = decimal.Parse(node.GetProperty("duration").GetString()!, NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture);
        var us = checked((long)decimal.Round(seconds * 1_000_000, 0, MidpointRounding.AwayFromZero));
        if (us <= 0) throw new FinalVideoQaException("RUNTIME_MISMATCH");
        return us;
    }
    private static (long, long) Rational(string? value)
    {
        var parts = (value ?? "").Split('/');
        if (parts.Length != 2 || !long.TryParse(parts[0], NumberStyles.None, CultureInfo.InvariantCulture, out var n)
            || !long.TryParse(parts[1], NumberStyles.None, CultureInfo.InvariantCulture, out var d) || n <= 0 || d <= 0)
            throw new FinalVideoQaException("OUTPUT_PROFILE_MISMATCH");
        return (n, d);
    }
    internal static (int Width, int Height) Dimensions(string profile) => profile switch
    {
        "video.landscape.v1" => (832, 480), "video.vertical.v1" => (480, 832), "video.square.v1" => (640, 640),
        _ => throw new FinalVideoQaException("OUTPUT_PROFILE_MISMATCH"),
    };
    public static void Validate(FinalQaObservedMedia facts, string profile, bool narration, long frames, long targetMs)
    {
        var (width, height) = Dimensions(profile);
        var video = facts.Video;
        if (facts.ContainerFamily != "mp4" || facts.FormatDurationUs <= 0) throw new FinalVideoQaException("CONTAINER_INVALID");
        if (video.Index != 0 || video.CodecName != "h264" || video.PixelFormat != "yuv420p"
            || video.DurationUs <= 0 || video.PacketCount is <= 0) throw new FinalVideoQaException("VIDEO_STREAM_INVALID");
        if (video.Width != width || video.Height != height || video.FpsNumerator <= 0 || video.FpsDenominator <= 0
            || (BigInteger)video.FpsNumerator != (BigInteger)24 * video.FpsDenominator)
            throw new FinalVideoQaException("OUTPUT_PROFILE_MISMATCH");
        var audio = facts.Audio;
        if (narration && (audio is null || audio.Index != 1 || audio.CodecName != "aac" || audio.Profile != "LC"
            || audio.SampleRate != 48000 || audio.Channels != 1 || audio.ChannelLayout is not (null or "mono") || audio.DurationUs <= 0)
            || !narration && audio is not null) throw new FinalVideoQaException("AUDIO_STREAM_INVALID");
        if (facts.StreamCount != (narration ? 2 : 1)) throw new FinalVideoQaException("UNEXPECTED_STREAM");
        if (frames <= 0 || targetMs <= 0) throw new FinalVideoQaException("INPUT_INVALID");
        BigInteger visual = (BigInteger)frames * 1_000_000;
        BigInteger target = (BigInteger)targetMs * 1000 * 24;
        var delta = BigInteger.Abs(visual - target);
        const int frameCeil = 41667;
        if (BigInteger.Abs((BigInteger)video.DurationUs * 24 - visual) > frameCeil * 24
            || BigInteger.Abs((BigInteger)video.DurationUs * 24 - target) > delta + frameCeil * 24
            || video.PacketCount is long packets && BigInteger.Abs((BigInteger)video.DurationUs * 24 - (BigInteger)packets * 1_000_000) > frameCeil * 24
            || BigInteger.Abs((BigInteger)facts.FormatDurationUs * 24 - target) > delta + 100_000 * 24
            || audio is not null && BigInteger.Abs((BigInteger)audio.DurationUs - (BigInteger)targetMs * 1000) > 100_000
            || BigInteger.Abs((BigInteger)facts.FormatDurationUs - Math.Max(video.DurationUs, audio?.DurationUs ?? 0)) > 100_000)
            throw new FinalVideoQaException("RUNTIME_MISMATCH");
    }
}
