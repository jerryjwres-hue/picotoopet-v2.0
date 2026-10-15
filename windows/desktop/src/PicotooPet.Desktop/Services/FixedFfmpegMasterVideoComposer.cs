using System.Buffers.Binary;
using System.Diagnostics;
using System.Globalization;
using System.Security.Cryptography;

namespace PicotooPet.Desktop.Services;

/// <summary>
/// C009B 使用点路径策略：只接受本地盘符完全限定路径。纯字符串检查，不触碰文件系统，
/// 因此对抗性路径（UNC、设备路径、根相对路径等）不会触发任何网络或设备访问。
/// </summary>
public static class MasterVideoPathPolicy
{
    private const int MaximumPathLength = 4096;
    private const string InvalidPathCharacters = "<>\"|?*";
    private static readonly HashSet<string> ReservedDeviceNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    };

    /// <summary>形如 C:\dir\file 的本地路径；拒绝 UNC、\\?\、\\.\、根相对、盘符相对、ADS、保留设备名与 ./.. 段。</summary>
    public static bool IsSafeLocalFullyQualified(string? path)
    {
        if (string.IsNullOrWhiteSpace(path) || path.Length > MaximumPathLength)
        {
            return false;
        }
        if (path.StartsWith(@"\\", StringComparison.Ordinal) || path.StartsWith("//", StringComparison.Ordinal))
        {
            return false; // UNC、\\?\ 扩展路径与 \\.\ 设备路径
        }
        if (path.Any(static character => character < ' ' || InvalidPathCharacters.Contains(character)))
        {
            return false;
        }
        if (path.Length < 3
            || !char.IsAsciiLetter(path[0])
            || path[1] != ':'
            || path[2] is not ('\\' or '/')
            || path.IndexOf(':', 2) >= 0 // 备用数据流
            || !Path.IsPathFullyQualified(path))
        {
            return false;
        }
        foreach (var segment in path[3..].Split('\\', '/'))
        {
            if (segment.Length == 0)
            {
                continue;
            }
            if (segment is "." or ".."
                || segment[^1] is '.' or ' '
                || ReservedDeviceNames.Contains(segment.Split('.')[0].TrimEnd(' ')))
            {
                return false;
            }
        }
        return true;
    }

    /// <summary>父目录必须存在且不是重解析点（符号链接/联接）；叶文件另由 IsOrdinaryFile 保证。</summary>
    public static bool HasOrdinaryParentDirectory(string path)
    {
        var parent = Path.GetDirectoryName(Path.GetFullPath(path));
        if (string.IsNullOrEmpty(parent) || !Directory.Exists(parent))
        {
            return false;
        }
        return (File.GetAttributes(parent) & FileAttributes.ReparsePoint) == 0;
    }
}

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
    /// <summary>与冻结的 C009A 叙述契约一致：单个 WAV 上限。</summary>
    public const long MaximumWavBytes = 32L * 1024 * 1024;
    /// <summary>与冻结的 C009A 叙述契约一致：所有 WAV 总量上限。</summary>
    public const long MaximumNarrationBytes = 256L * 1024 * 1024;
    /// <summary>仅拒绝明显无效的 mux 输出；最终交付 QA 容差属于 C010。</summary>
    public const double DurationToleranceSeconds = 0.25;
    private const int MinimumWavSampleRate = 8_000;
    private const int MaximumWavSampleRate = 48_000;
    private const int MaximumWavChunks = 64;

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
        // 已验证的输入在整个使用期间持有只读共享句柄（拒绝写入/删除/重命名替换），
        // 把“哈希校验 → ffprobe → ffmpeg 读取”之间的替换窗口关闭。
        var leases = new List<FileStream>();
        try
        {
            var (visualLease, _) = await OpenVerifiedAsync(
                request.Visual.Path, request.Visual.Bytes, request.Visual.Sha256,
                maximumBytes: 0, captureBytes: false,
                MasterVideoComposerException.VisualInvalid, cancellationToken).ConfigureAwait(false);
            leases.Add(visualLease);
            if (segments.Count == 0)
            {
                await CopyVisualAsync(request, visualLease, cancellationToken).ConfigureAwait(false);
                return;
            }
            await ComposeNarratedAsync(request, segments, leases, cancellationToken).ConfigureAwait(false);
        }
        catch
        {
            // 失败、取消、超时：不得留下任何输出；只删除 C009A 提供的临时输出，绝不触碰来源。
            TryDelete(request.OutputPath);
            throw;
        }
        finally
        {
            foreach (var lease in leases)
            {
                await lease.DisposeAsync().ConfigureAwait(false);
            }
        }
    }

    // ── 请求形状（防御性：C009A 已验证，这里在进程使用前重复检查）─────────────────────────────
    private static IReadOnlyList<VerifiedMasterNarrationSegment> ValidateRequest(MasterVideoCompositionRequest request)
    {
        if (request?.Visual is null
            || request.NarrationSegments is null
            || string.IsNullOrWhiteSpace(request.OutputPath)
            || string.IsNullOrWhiteSpace(request.Visual.Path)
            || request.TargetRuntimeMs is <= 0 or > MaximumTargetRuntimeMs
            || request.NarrationSegments.Count > MaximumSegments)
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.RequestInvalid);
        }
        // 路径策略先于任何文件系统访问：UNC/设备/根相对路径不会引发网络或设备 I/O。
        if (!MasterVideoPathPolicy.IsSafeLocalFullyQualified(request.OutputPath)
            || !MasterVideoPathPolicy.IsSafeLocalFullyQualified(request.Visual.Path))
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.PathInvalid);
        }
        if (!string.Equals(Path.GetFileName(request.OutputPath), OutputFileName, StringComparison.OrdinalIgnoreCase)
            || string.Equals(
                Path.GetFullPath(request.OutputPath), Path.GetFullPath(request.Visual.Path),
                StringComparison.OrdinalIgnoreCase))
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.RequestInvalid);
        }

        var ordered = request.NarrationSegments;
        long previousEnd = 0;
        long totalBytes = 0;
        for (var index = 0; index < ordered.Count; index++)
        {
            var segment = ordered[index];
            if (segment is null || !MasterVideoPathPolicy.IsSafeLocalFullyQualified(segment.WavPath))
            {
                throw new MasterVideoComposerException(
                    segment is null
                        ? MasterVideoComposerException.NarrationInvalid
                        : MasterVideoComposerException.PathInvalid);
            }
            if (string.Equals(
                    Path.GetFullPath(segment.WavPath), Path.GetFullPath(request.OutputPath),
                    StringComparison.OrdinalIgnoreCase)
                || string.Equals(
                    Path.GetFullPath(segment.WavPath), Path.GetFullPath(request.Visual.Path),
                    StringComparison.OrdinalIgnoreCase))
            {
                throw new MasterVideoComposerException(MasterVideoComposerException.PathInvalid);
            }
            if (segment.Order != index + 1
                || segment.StartMs < 0
                || segment.EndMs <= segment.StartMs
                || segment.EndMs > request.TargetRuntimeMs
                || segment.StartMs < previousEnd
                || segment.Sha256 is not { Length: 64 }
                || segment.Bytes <= 0
                || segment.Bytes > MaximumWavBytes
                || (totalBytes += segment.Bytes) > MaximumNarrationBytes
                || segment.Channels is < 1 or > 2
                || segment.SampleRate is < MinimumWavSampleRate or > MaximumWavSampleRate
                || segment.SampleFrames <= 0)
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

        // 文件系统检查：输出目录、视觉与各 WAV 的父目录都必须存在且不是重解析点；输出必须尚不存在。
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
        if (!MasterVideoPathPolicy.HasOrdinaryParentDirectory(request.Visual.Path)
            || ordered.Any(static segment => !MasterVideoPathPolicy.HasOrdinaryParentDirectory(segment.WavPath)))
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.PathInvalid);
        }
        return ordered;
    }

    /// <summary>
    /// 打开并校验输入，返回的只读共享句柄由调用方持有到 mux 结束。
    /// 校验：普通文件（打开前后各一次）、字节数、可选上限、SHA-256。
    /// </summary>
    private static async Task<(FileStream Stream, byte[]? Bytes)> OpenVerifiedAsync(
        string path,
        long expectedBytes,
        string expectedSha256,
        long maximumBytes,
        bool captureBytes,
        string failureCode,
        CancellationToken cancellationToken)
    {
        FileStream? stream = null;
        try
        {
            if (!ProductionLocalEnvironment.IsOrdinaryFile(path)
                || (maximumBytes > 0 && expectedBytes > maximumBytes))
            {
                throw new MasterVideoComposerException(failureCode);
            }
            stream = new FileStream(
                path, FileMode.Open, FileAccess.Read, FileShare.Read, 81920,
                FileOptions.Asynchronous | FileOptions.SequentialScan);
            // 打开后复查：叶节点仍是普通文件（非链接），实际长度与声明一致且不超上限。
            if (!ProductionLocalEnvironment.IsOrdinaryFile(path)
                || stream.Length != expectedBytes
                || (maximumBytes > 0 && stream.Length > maximumBytes))
            {
                throw new MasterVideoComposerException(failureCode);
            }
            byte[]? bytes = null;
            string actual;
            if (captureBytes)
            {
                // 有界读取（≤ MaximumWavBytes）：同一次读取既做哈希也做解析，避免二次读取。
                bytes = new byte[(int)stream.Length];
                await stream.ReadExactlyAsync(bytes, cancellationToken).ConfigureAwait(false);
                actual = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
            }
            else
            {
                actual = Convert.ToHexString(
                    await SHA256.HashDataAsync(stream, cancellationToken).ConfigureAwait(false)).ToLowerInvariant();
                stream.Position = 0;
            }
            if (!string.Equals(actual, expectedSha256, StringComparison.Ordinal))
            {
                throw new MasterVideoComposerException(failureCode);
            }
            return (stream, bytes);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            if (stream is not null)
            {
                await stream.DisposeAsync().ConfigureAwait(false);
            }
            throw new MasterVideoComposerException(failureCode, exception);
        }
        catch
        {
            if (stream is not null)
            {
                await stream.DisposeAsync().ConfigureAwait(false);
            }
            throw;
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
        FileStream verifiedVisual,
        CancellationToken cancellationToken)
    {
        verifiedVisual.Position = 0;
        await using (var destination = new FileStream(
            request.OutputPath, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1024 * 1024,
            FileOptions.Asynchronous))
        {
            await verifiedVisual.CopyToAsync(destination, 1024 * 1024, cancellationToken).ConfigureAwait(false);
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
        List<FileStream> leases,
        CancellationToken cancellationToken)
    {
        foreach (var segment in segments)
        {
            leases.Add(await VerifyNarrationAsync(segment, cancellationToken).ConfigureAwait(false));
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

    /// <summary>
    /// 使用点重验 WAV：普通文件、字节数（≤ 32 MiB）、SHA-256、严格 PCM16 头部、精确窗口。
    /// 返回的只读共享句柄由调用方持有到 mux 结束。
    /// </summary>
    private static async Task<FileStream> VerifyNarrationAsync(
        VerifiedMasterNarrationSegment segment,
        CancellationToken cancellationToken)
    {
        var (stream, bytes) = await OpenVerifiedAsync(
            segment.WavPath, segment.Bytes, segment.Sha256,
            MaximumWavBytes, captureBytes: true,
            MasterVideoComposerException.NarrationInvalid, cancellationToken).ConfigureAwait(false);
        try
        {
            if (!TryParsePcm16(bytes!, out var rate, out var channels, out var frames)
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
            return stream;
        }
        catch
        {
            await stream.DisposeAsync().ConfigureAwait(false);
            throw;
        }
    }

    /// <summary>
    /// 严格 PCM16 WAV：与冻结的 C009A ParseWav 同等严格（RIFF 长度、blockAlign/byteRate、重复 fmt/data、
    /// 采样率范围），并限制 chunk 数量。任何异常头部都返回 false，由调用方映射为封闭错误码。
    /// </summary>
    public static bool TryParsePcm16(ReadOnlySpan<byte> file, out int rate, out int channels, out long frames)
    {
        rate = 0;
        channels = 0;
        frames = 0;
        if (file.Length < 44
            || file.Length > MaximumWavBytes
            || !file[..4].SequenceEqual("RIFF"u8)
            || !file.Slice(8, 4).SequenceEqual("WAVE"u8)
            || BinaryPrimitives.ReadUInt32LittleEndian(file.Slice(4, 4)) + 8u != (uint)file.Length)
        {
            return false;
        }
        var haveFormat = false;
        var haveData = false;
        var blockAlign = 0;
        var byteRate = 0;
        long dataBytes = 0;
        var offset = 12;
        for (var chunks = 0; offset <= file.Length - 8; chunks++)
        {
            if (chunks >= MaximumWavChunks)
            {
                return false;
            }
            var id = file.Slice(offset, 4);
            var size = (long)BinaryPrimitives.ReadUInt32LittleEndian(file.Slice(offset + 4, 4));
            var body = offset + 8;
            if (size > file.Length - body)
            {
                return false;
            }
            if (id.SequenceEqual("fmt "u8))
            {
                if (haveFormat || size < 16)
                {
                    return false;
                }
                haveFormat = true;
                var format = BinaryPrimitives.ReadUInt16LittleEndian(file.Slice(body, 2));
                channels = BinaryPrimitives.ReadUInt16LittleEndian(file.Slice(body + 2, 2));
                rate = (int)BinaryPrimitives.ReadUInt32LittleEndian(file.Slice(body + 4, 4));
                byteRate = (int)BinaryPrimitives.ReadUInt32LittleEndian(file.Slice(body + 8, 4));
                blockAlign = BinaryPrimitives.ReadUInt16LittleEndian(file.Slice(body + 12, 2));
                var bits = BinaryPrimitives.ReadUInt16LittleEndian(file.Slice(body + 14, 2));
                if (format != 1 || bits != 16)
                {
                    return false;
                }
            }
            else if (id.SequenceEqual("data"u8))
            {
                if (haveData)
                {
                    return false;
                }
                haveData = true;
                dataBytes = size;
            }
            offset = checked(body + (int)size + (int)(size & 1));
        }
        if (!haveFormat || !haveData
            || channels is < 1 or > 2
            || rate is < MinimumWavSampleRate or > MaximumWavSampleRate
            || blockAlign != channels * 2
            || byteRate != rate * blockAlign
            || dataBytes <= 0
            || dataBytes % blockAlign != 0)
        {
            return false;
        }
        frames = dataBytes / blockAlign;
        return frames * 1_000L / rate > 0;
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
