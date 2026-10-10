using System.Buffers.Binary;
using System.Diagnostics;
using System.Globalization;

namespace PicotooPet.Desktop.Services;

/// <summary>
/// C009B：C009A 冻结接口之后的固定 Windows 媒体合成器。视频只做 stream-copy；旁白为 AAC-LC/48 kHz/单声道/128 kbps；
/// 没有调用方可控的可执行文件、编解码器、码率、采样率、声道、滤镜、路径或网络权限。
/// </summary>
public sealed class FixedFfmpegMasterVideoComposer : IMasterVideoComposer
{
    public const string OutputFileName = "master.mp4";
    public const long MaximumTargetRuntimeMs = 600_000;
    public const int MaximumSegments = 60;
    public const int AudioSampleRate = 48_000;
    /// <summary>仅拒绝明显无效的 mux 输出；最终交付 QA 容差属于 C010。</summary>
    public const double DurationToleranceSeconds = 0.25;
    private const int MinimumWavSampleRate = 8_000;
    private const int MaximumWavSampleRate = 192_000;

    private static readonly TimeSpan DefaultMuxTimeout = TimeSpan.FromMinutes(10);
    private static readonly TimeSpan DefaultProbeTimeout = TimeSpan.FromSeconds(30);

    private readonly IMasterVideoProcessRunner _runner;
    private readonly MasterVideoMediaProbe _probe;
    private readonly TimeSpan _muxTimeout;

    public FixedFfmpegMasterVideoComposer()
        : this(new FixedMasterVideoProcessRunner())
    {
    }

    public FixedFfmpegMasterVideoComposer(IMasterVideoProcessRunner runner)
        : this(runner, DefaultMuxTimeout, DefaultProbeTimeout)
    {
    }

    public FixedFfmpegMasterVideoComposer(
        IMasterVideoProcessRunner runner,
        TimeSpan muxTimeout,
        TimeSpan probeTimeout)
    {
        _runner = runner ?? throw new ArgumentNullException(nameof(runner));
        _probe = new MasterVideoMediaProbe(runner, probeTimeout);
        _muxTimeout = muxTimeout;
    }

    public async Task ComposeAsync(
        MasterVideoCompositionRequest request,
        CancellationToken cancellationToken)
    {
        var segments = ValidateRequest(request);
        try
        {
            await VerifyVisualAsync(request.Visual, cancellationToken).ConfigureAwait(false);
            if (segments.Count == 0)
            {
                await CopyVisualAsync(request, cancellationToken).ConfigureAwait(false);
                return;
            }
            await ComposeNarratedAsync(request, segments, cancellationToken).ConfigureAwait(false);
        }
        catch
        {
            // 失败、取消、超时：不得留下任何输出；只删除 C009A 提供的临时输出，绝不触碰来源。
            TryDelete(request.OutputPath);
            throw;
        }
    }

    // ── 请求形状（防御性：C009A 已验证，这里在进程使用前重复检查）─────────────────────────────
    private static IReadOnlyList<VerifiedMasterNarrationSegment> ValidateRequest(MasterVideoCompositionRequest request)
    {
        if (request?.Visual is null
            || request.NarrationSegments is null
            || string.IsNullOrWhiteSpace(request.OutputPath)
            || string.IsNullOrWhiteSpace(request.Visual.Path)
            || !Path.IsPathRooted(request.OutputPath)
            || !Path.IsPathRooted(request.Visual.Path)
            || request.TargetRuntimeMs is <= 0 or > MaximumTargetRuntimeMs
            || request.NarrationSegments.Count > MaximumSegments
            || !string.Equals(Path.GetFileName(request.OutputPath), OutputFileName, StringComparison.OrdinalIgnoreCase)
            || string.Equals(
                Path.GetFullPath(request.OutputPath), Path.GetFullPath(request.Visual.Path),
                StringComparison.OrdinalIgnoreCase))
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.RequestInvalid);
        }
        var outputDirectory = Path.GetDirectoryName(Path.GetFullPath(request.OutputPath));
        if (outputDirectory is null || !Directory.Exists(outputDirectory) || File.Exists(request.OutputPath)
            || Directory.Exists(request.OutputPath))
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.RequestInvalid);
        }
        try
        {
            ProductionLocalEnvironment.AssertNoLinkEscape(outputDirectory, outputDirectory);
        }
        catch (InvalidDataException exception)
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.RequestInvalid, exception);
        }

        var ordered = request.NarrationSegments;
        long previousEnd = 0;
        for (var index = 0; index < ordered.Count; index++)
        {
            var segment = ordered[index];
            if (segment is null
                || segment.Order != index + 1
                || segment.StartMs < 0
                || segment.EndMs <= segment.StartMs
                || segment.EndMs > request.TargetRuntimeMs
                || segment.StartMs < previousEnd
                || segment.Sha256 is not { Length: 64 }
                || segment.Bytes <= 0
                || segment.Channels is < 1 or > 2
                || segment.SampleRate is < MinimumWavSampleRate or > MaximumWavSampleRate
                || segment.SampleFrames <= 0
                || !Path.IsPathRooted(segment.WavPath))
            {
                throw new MasterVideoComposerException(MasterVideoComposerException.NarrationInvalid);
            }
            // 精确 [StartMs, EndMs) 窗口：样本帧数不得超过窗口；永不截断或加速。
            if (segment.SampleFrames * 1_000L > (segment.EndMs - segment.StartMs) * (long)segment.SampleRate)
            {
                throw new MasterVideoComposerException(MasterVideoComposerException.SegmentTooLong);
            }
            previousEnd = segment.EndMs;
        }
        return ordered;
    }

    private static async Task VerifyVisualAsync(VerifiedMasterVisual visual, CancellationToken cancellationToken)
    {
        if (!await MatchesAsync(visual.Path, visual.Bytes, visual.Sha256, cancellationToken).ConfigureAwait(false))
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.VisualInvalid);
        }
    }

    private static async Task<bool> MatchesAsync(
        string path,
        long expectedBytes,
        string expectedSha256,
        CancellationToken cancellationToken)
    {
        if (!ProductionLocalEnvironment.IsOrdinaryFile(path) || new FileInfo(path).Length != expectedBytes)
        {
            return false;
        }
        var actual = await ProductionLocalEnvironment.Sha256FileAsync(path, cancellationToken).ConfigureAwait(false);
        return string.Equals(actual, expectedSha256, StringComparison.Ordinal);
    }

    // ── 无旁白：逐字节复制，不调用 ffmpeg，不引入音频，不重写元数据 ───────────────────────────
    private static async Task CopyVisualAsync(
        MasterVideoCompositionRequest request,
        CancellationToken cancellationToken)
    {
        await using (var source = new FileStream(
            request.Visual.Path, FileMode.Open, FileAccess.Read, FileShare.Read, 1024 * 1024,
            FileOptions.Asynchronous | FileOptions.SequentialScan))
        await using (var destination = new FileStream(
            request.OutputPath, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1024 * 1024,
            FileOptions.Asynchronous))
        {
            await source.CopyToAsync(destination, 1024 * 1024, cancellationToken).ConfigureAwait(false);
            await destination.FlushAsync(cancellationToken).ConfigureAwait(false);
        }
        if (!await MatchesAsync(request.OutputPath, request.Visual.Bytes, request.Visual.Sha256, cancellationToken)
                .ConfigureAwait(false))
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.OutputInvalid);
        }
    }

    // ── 有旁白：固定 stream-copy + AAC mux ─────────────────────────────────────────────────
    private async Task ComposeNarratedAsync(
        MasterVideoCompositionRequest request,
        IReadOnlyList<VerifiedMasterNarrationSegment> segments,
        CancellationToken cancellationToken)
    {
        foreach (var segment in segments)
        {
            await VerifyNarrationAsync(segment, cancellationToken).ConfigureAwait(false);
        }

        var input = await _probe.ProbeAsync(request.Visual.Path, cancellationToken).ConfigureAwait(false);
        ValidateInputMedia(input, request.TargetRuntimeMs);

        var startInfo = new ProcessStartInfo
        {
            FileName = FixedMasterVideoProcessRunner.Ffmpeg,
            UseShellExecute = false,
            WorkingDirectory = Path.GetDirectoryName(Path.GetFullPath(request.OutputPath))!,
        };
        foreach (var argument in BuildMuxArguments(
                     request.Visual.Path, segments, request.TargetRuntimeMs, request.OutputPath))
        {
            startInfo.ArgumentList.Add(argument);
        }
        var result = await _runner.RunAsync(startInfo, _muxTimeout, cancellationToken).ConfigureAwait(false);
        if (result.TimedOut)
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.FfmpegTimeout);
        }
        if (result.ExitCode != 0)
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.FfmpegFailed);
        }
        if (!ProductionLocalEnvironment.IsOrdinaryFile(request.OutputPath) || new FileInfo(request.OutputPath).Length <= 0)
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.OutputInvalid);
        }

        var output = await _probe.ProbeAsync(request.OutputPath, cancellationToken).ConfigureAwait(false);
        ValidateOutputMedia(input, output, request.TargetRuntimeMs);
    }

    /// <summary>使用点重验 WAV 内容：普通文件、字节数、SHA-256、PCM16 事实、精确窗口。</summary>
    private static async Task VerifyNarrationAsync(
        VerifiedMasterNarrationSegment segment,
        CancellationToken cancellationToken)
    {
        if (!await MatchesAsync(segment.WavPath, segment.Bytes, segment.Sha256, cancellationToken).ConfigureAwait(false))
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.NarrationInvalid);
        }
        var bytes = await File.ReadAllBytesAsync(segment.WavPath, cancellationToken).ConfigureAwait(false);
        if (!TryParsePcm16(bytes, out var rate, out var channels, out var frames)
            || rate != segment.SampleRate
            || channels != segment.Channels
            || frames != segment.SampleFrames)
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.NarrationInvalid);
        }
        if (frames * 1_000L > (segment.EndMs - segment.StartMs) * (long)rate)
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.SegmentTooLong);
        }
    }

    private static bool TryParsePcm16(ReadOnlySpan<byte> file, out int rate, out int channels, out long frames)
    {
        rate = 0;
        channels = 0;
        frames = 0;
        if (file.Length < 45 || !file[..4].SequenceEqual("RIFF"u8) || !file.Slice(8, 4).SequenceEqual("WAVE"u8))
        {
            return false;
        }
        var haveFormat = false;
        var offset = 12;
        while (offset + 8 <= file.Length)
        {
            var id = file.Slice(offset, 4);
            var size = (long)BinaryPrimitives.ReadUInt32LittleEndian(file.Slice(offset + 4, 4));
            var body = offset + 8;
            if (id.SequenceEqual("fmt "u8))
            {
                if (size < 16 || body + 16 > file.Length)
                {
                    return false;
                }
                var format = BinaryPrimitives.ReadUInt16LittleEndian(file.Slice(body, 2));
                channels = BinaryPrimitives.ReadUInt16LittleEndian(file.Slice(body + 2, 2));
                rate = (int)BinaryPrimitives.ReadUInt32LittleEndian(file.Slice(body + 4, 4));
                var bits = BinaryPrimitives.ReadUInt16LittleEndian(file.Slice(body + 14, 2));
                haveFormat = format == 1 && bits == 16;
            }
            else if (id.SequenceEqual("data"u8))
            {
                if (!haveFormat || channels is < 1 or > 2 || size <= 0 || body + size > file.Length
                    || size % (channels * 2L) != 0)
                {
                    return false;
                }
                frames = size / (channels * 2L);
                return true;
            }
            offset = (int)Math.Min(int.MaxValue, body + size + (size & 1));
        }
        return false;
    }

    private static void ValidateInputMedia(MasterMediaFacts facts, long targetRuntimeMs)
    {
        if (facts.VideoStreams != 1 || facts.AudioStreams != 0 || facts.OtherStreams != 0
            || facts.Video is not { } video
            || video.Codec != "h264"
            || video.PixelFormat != "yuv420p"
            || video.Width <= 0 || video.Height <= 0
            || video.FrameRateNumerator <= 0 || video.FrameRateDenominator <= 0
            || video.PacketCount <= 0
            || facts.DurationSeconds <= 0
            || Math.Abs(facts.DurationSeconds - (targetRuntimeMs / 1000.0)) > DurationToleranceSeconds)
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.VisualInvalid);
        }
    }

    private static void ValidateOutputMedia(MasterMediaFacts input, MasterMediaFacts output, long targetRuntimeMs)
    {
        var source = input.Video!;
        if (output.VideoStreams != 1 || output.AudioStreams != 1 || output.OtherStreams != 0
            || output.Video is not { } video
            || output.Audio is not { } audio
            || video.Codec != "h264"
            || video.PixelFormat != "yuv420p"
            || video.Width != source.Width
            || video.Height != source.Height
            || video.FrameRateNumerator * source.FrameRateDenominator != source.FrameRateNumerator * video.FrameRateDenominator
            || video.PacketCount != source.PacketCount
            || audio.Codec != "aac"
            || audio.Profile != "LC"
            || audio.SampleRate != AudioSampleRate
            || audio.Channels != 1
            || output.DurationSeconds <= 0
            || Math.Abs(output.DurationSeconds - (targetRuntimeMs / 1000.0)) > DurationToleranceSeconds)
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.OutputInvalid);
        }
    }

    // ── 固定命令与滤镜图：只由已验证的整数时间事实生成 ─────────────────────────────────────────
    private static string Seconds(long milliseconds) =>
        string.Create(CultureInfo.InvariantCulture, $"{milliseconds / 1000}.{milliseconds % 1000:D3}");

    /// <summary>
    /// 单声道保持幅度；立体声显式 0.5/0.5 平均下混（不依赖 FFmpeg 隐式下混）。
    /// 每段：归一化到 48 kHz 单声道 → 精确 StartMs 延迟；无 trim、无变速。
    /// </summary>
    public static string BuildFilterComplex(
        IReadOnlyList<VerifiedMasterNarrationSegment> segments,
        long targetRuntimeMs)
    {
        var parts = new List<string>();
        for (var index = 0; index < segments.Count; index++)
        {
            var segment = segments[index];
            var downmix = segment.Channels == 2 ? "pan=mono|c0=0.5*c0+0.5*c1," : string.Empty;
            parts.Add(string.Create(
                CultureInfo.InvariantCulture,
                $"[{index + 1}:a]{downmix}aformat=sample_rates={AudioSampleRate}:channel_layouts=mono:sample_fmts=fltp,"
                + $"adelay={segment.StartMs}:all=1[a{index}]"));
        }
        var inputs = string.Concat(Enumerable.Range(0, segments.Count).Select(index => $"[a{index}]"));
        parts.Add(string.Create(
            CultureInfo.InvariantCulture,
            $"{inputs}amix=inputs={segments.Count}:duration=longest:normalize=0,apad=whole_dur={Seconds(targetRuntimeMs)}[aout]"));
        return string.Join(';', parts);
    }

    public static IReadOnlyList<string> BuildMuxArguments(
        string visualPath,
        IReadOnlyList<VerifiedMasterNarrationSegment> segments,
        long targetRuntimeMs,
        string outputPath)
    {
        var arguments = new List<string> { "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", visualPath };
        foreach (var segment in segments)
        {
            arguments.Add("-i");
            arguments.Add(segment.WavPath);
        }
        arguments.AddRange(
        [
            "-filter_complex", BuildFilterComplex(segments, targetRuntimeMs),
            "-map", "0:v:0", "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k",
            "-ar", AudioSampleRate.ToString(CultureInfo.InvariantCulture), "-ac", "1",
            "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact",
            "-movflags", "+faststart",
            "-f", "mp4", outputPath,
        ]);
        return arguments;
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (!string.IsNullOrEmpty(path) && File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (IOException)
        {
            // 位于 C009A 临时目录内；其清理由 C009A 的 finally 兜底。
        }
        catch (UnauthorizedAccessException)
        {
            // 同上。
        }
    }
}
