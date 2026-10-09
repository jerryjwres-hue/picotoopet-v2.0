using System.Diagnostics;
using System.Globalization;
using System.Text.Json;

namespace PicotooPet.Desktop.Services;

public sealed record MasterVideoStreamFacts(
    string Codec,
    string PixelFormat,
    int Width,
    int Height,
    long FrameRateNumerator,
    long FrameRateDenominator,
    long PacketCount);

public sealed record MasterAudioStreamFacts(string Codec, string Profile, int SampleRate, int Channels);

public sealed record MasterMediaFacts(
    int VideoStreams,
    int AudioStreams,
    int OtherStreams,
    MasterVideoStreamFacts? Video,
    MasterAudioStreamFacts? Audio,
    double DurationSeconds);

/// <summary>ffprobe JSON 的封闭字段读取；畸形/未知形状一律有界失败，原始 JSON 永不持久化。</summary>
public sealed class MasterVideoMediaProbe
{
    private static readonly TimeSpan ProbeTimeout = TimeSpan.FromSeconds(30);
    private readonly IMasterVideoProcessRunner _runner;
    private readonly TimeSpan _timeout;

    public MasterVideoMediaProbe(IMasterVideoProcessRunner runner)
        : this(runner, ProbeTimeout)
    {
    }

    public MasterVideoMediaProbe(IMasterVideoProcessRunner runner, TimeSpan timeout)
    {
        _runner = runner ?? throw new ArgumentNullException(nameof(runner));
        _timeout = timeout;
    }

    public async Task<MasterMediaFacts> ProbeAsync(string mediaPath, CancellationToken cancellationToken)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = FixedMasterVideoProcessRunner.Ffprobe,
            UseShellExecute = false,
            WorkingDirectory = Path.GetDirectoryName(mediaPath) ?? string.Empty,
        };
        foreach (var argument in new[]
        {
            "-v", "error", "-count_packets",
            "-show_entries",
            "stream=codec_type,codec_name,profile,width,height,r_frame_rate,pix_fmt,sample_rate,channels,nb_read_packets:format=duration",
            "-of", "json", mediaPath,
        })
        {
            startInfo.ArgumentList.Add(argument);
        }
        var result = await _runner.RunAsync(startInfo, _timeout, cancellationToken).ConfigureAwait(false);
        if (result.TimedOut)
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.FfmpegTimeout);
        }
        if (result.ExitCode != 0)
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.ProbeInvalid);
        }
        return Parse(result.Stdout);
    }

    public static MasterMediaFacts Parse(string json)
    {
        try
        {
            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;
            MasterVideoStreamFacts? video = null;
            MasterAudioStreamFacts? audio = null;
            int videos = 0, audios = 0, others = 0;
            foreach (var stream in root.GetProperty("streams").EnumerateArray())
            {
                switch (stream.GetProperty("codec_type").GetString())
                {
                    case "video":
                        videos++;
                        var (numerator, denominator) = ParseRational(stream.GetProperty("r_frame_rate").GetString());
                        video = new MasterVideoStreamFacts(
                            stream.GetProperty("codec_name").GetString() ?? string.Empty,
                            stream.GetProperty("pix_fmt").GetString() ?? string.Empty,
                            stream.GetProperty("width").GetInt32(),
                            stream.GetProperty("height").GetInt32(),
                            numerator,
                            denominator,
                            long.Parse(stream.GetProperty("nb_read_packets").GetString() ?? "0", CultureInfo.InvariantCulture));
                        break;
                    case "audio":
                        audios++;
                        audio = new MasterAudioStreamFacts(
                            stream.GetProperty("codec_name").GetString() ?? string.Empty,
                            stream.TryGetProperty("profile", out var profile) ? profile.GetString() ?? string.Empty : string.Empty,
                            int.Parse(stream.GetProperty("sample_rate").GetString() ?? "0", CultureInfo.InvariantCulture),
                            stream.GetProperty("channels").GetInt32());
                        break;
                    default:
                        others++;
                        break;
                }
            }
            var duration = double.Parse(
                root.GetProperty("format").GetProperty("duration").GetString() ?? string.Empty,
                CultureInfo.InvariantCulture);
            return new MasterMediaFacts(videos, audios, others, video, audio, duration);
        }
        catch (Exception exception) when (exception is JsonException
            or KeyNotFoundException
            or InvalidOperationException
            or FormatException
            or OverflowException)
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.ProbeInvalid, exception);
        }
    }

    private static (long Numerator, long Denominator) ParseRational(string? value)
    {
        var parts = (value ?? string.Empty).Split('/');
        if (parts.Length != 2
            || !long.TryParse(parts[0], NumberStyles.None, CultureInfo.InvariantCulture, out var numerator)
            || !long.TryParse(parts[1], NumberStyles.None, CultureInfo.InvariantCulture, out var denominator))
        {
            throw new FormatException("frame rate");
        }
        return (numerator, denominator);
    }
}
