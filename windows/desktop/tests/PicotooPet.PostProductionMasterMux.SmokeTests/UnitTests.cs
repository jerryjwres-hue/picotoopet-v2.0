using System.Diagnostics;
using System.Text;
using System.Text.RegularExpressions;
using PicotooPet.Desktop.Services;

namespace PicotooPet.PostProductionMasterMux.SmokeTests;

/// <summary>纯逻辑/假进程测试：真实文件系统 + 真实 composer，进程边界为假。</summary>
internal static class UnitTests
{
    private const long Target = 6000;

    public static async Task RunAsync()
    {
        await ZeroNarrationByteCopyAsync().ConfigureAwait(false);
        await TamperAndRequestValidationAsync().ConfigureAwait(false);
        await ExactWindowAsync().ConfigureAwait(false);
        GraphAndArgumentPolicy();
        await ProbeValidationAsync().ConfigureAwait(false);
        await TimeoutCancelAndErrorsAsync().ConfigureAwait(false);
        await ExecutablePolicyAsync().ConfigureAwait(false);
    }

    // ── 无旁白 ─────────────────────────────────────────────────────────────────────────────
    private static async Task ZeroNarrationByteCopyAsync()
    {
        using var env = Env.Create([]);
        var composer = new FixedFfmpegMasterVideoComposer(env.Runner);
        await composer.ComposeAsync(env.Request(), CancellationToken.None).ConfigureAwait(false);
        Check.Equal(0, env.Runner.Calls.Count, "零旁白不得调用任何进程（含 ffprobe）");
        Check.True(File.ReadAllBytes(env.OutputPath).AsSpan().SequenceEqual(env.VisualBytes), "输出必须与视觉字节逐字节相同");
        Check.Equal(env.Visual.Sha256, TestMedia.Sha(File.ReadAllBytes(env.OutputPath)), "输出 SHA 必须等于视觉 SHA");

        // 复制期间取消仍可观察，且不留输出。
        using var cancelled = Env.Create([]);
        using var source = new CancellationTokenSource();
        await source.CancelAsync().ConfigureAwait(false);
        try
        {
            await new FixedFfmpegMasterVideoComposer(cancelled.Runner)
                .ComposeAsync(cancelled.Request(), source.Token).ConfigureAwait(false);
            throw new InvalidOperationException("取消必须抛出");
        }
        catch (OperationCanceledException)
        {
            // 预期。
        }
        Check.True(!File.Exists(cancelled.OutputPath), "取消后不得留下输出");

        // 视觉被篡改 → 不复制。
        using var tampered = Env.Create([]);
        File.AppendAllText(tampered.Visual.Path, "x");
        await Check.ThrowsAsync(
            () => new FixedFfmpegMasterVideoComposer(tampered.Runner).ComposeAsync(tampered.Request(), CancellationToken.None),
            MasterVideoComposerException.VisualInvalid,
            "视觉被篡改必须拒绝").ConfigureAwait(false);
        Check.True(!File.Exists(tampered.OutputPath), "篡改后不得写输出");
    }

    // ── 篡改与请求校验：都不得启动进程 ───────────────────────────────────────────────────────
    private static async Task TamperAndRequestValidationAsync()
    {
        using var visual = Env.Create([Seg(1, 24000, 1, 24000, 0, 2000)]);
        File.AppendAllText(visual.Visual.Path, "x");
        await Check.ThrowsAsync(
            () => new FixedFfmpegMasterVideoComposer(visual.Runner).ComposeAsync(visual.Request(), CancellationToken.None),
            MasterVideoComposerException.VisualInvalid,
            "视觉 SHA 不匹配必须拒绝").ConfigureAwait(false);
        Check.Equal(0, visual.Runner.Calls.Count, "视觉篡改不得启动进程");

        using var wav = Env.Create([Seg(1, 24000, 1, 24000, 0, 2000)]);
        File.AppendAllText(wav.Segments[0].WavPath, "x");
        await Check.ThrowsAsync(
            () => new FixedFfmpegMasterVideoComposer(wav.Runner).ComposeAsync(wav.Request(), CancellationToken.None),
            MasterVideoComposerException.NarrationInvalid,
            "WAV 被篡改必须拒绝").ConfigureAwait(false);
        Check.Equal(0, wav.Runner.Calls.Count, "WAV 篡改不得启动进程");

        // 请求中的事实与 WAV 头不一致（声称单声道、实为立体声）。
        using var lie = Env.Create([Seg(1, 24000, 1, 24000, 0, 2000)]);
        var lying = lie.Segments[0] with { Channels = 2 };
        await Check.ThrowsAsync(
            () => new FixedFfmpegMasterVideoComposer(lie.Runner)
                .ComposeAsync(lie.Request(segments: [lying]), CancellationToken.None),
            MasterVideoComposerException.NarrationInvalid,
            "WAV 头与请求事实不一致必须拒绝").ConfigureAwait(false);
        Check.Equal(0, lie.Runner.Calls.Count, "事实不一致不得启动进程");

        // 无效顺序 / 重叠 / 越界 / 负起点 / 空窗口。
        var specs = new (string Name, Func<TestEnv, IReadOnlyList<VerifiedMasterNarrationSegment>> Make)[]
        {
            ("order-gap", env => [env.Segments[0] with { Order = 2 }]),
            ("overlap", env => [env.Segments[0], env.Segments[1] with { StartMs = 1000 }]),
            ("end-after-target", env => [env.Segments[0] with { EndMs = Target + 1 }]),
            ("negative-start", env => [env.Segments[0] with { StartMs = -1 }]),
            ("empty-window", env => [env.Segments[0] with { EndMs = env.Segments[0].StartMs }]),
        };
        foreach (var (name, make) in specs)
        {
            using var env = Env.Create([Seg(1, 24000, 1, 24000, 0, 2500), Seg(2, 24000, 1, 24000, 2500, 5000)]);
            await Check.ThrowsAsync(
                () => new FixedFfmpegMasterVideoComposer(env.Runner)
                    .ComposeAsync(env.Request(segments: make(env)), CancellationToken.None),
                MasterVideoComposerException.NarrationInvalid,
                $"{name} 必须拒绝").ConfigureAwait(false);
            Check.Equal(0, env.Runner.Calls.Count, $"{name} 不得启动进程");
            Check.True(!File.Exists(env.OutputPath), $"{name} 不得写输出");
        }

        // 输出路径：非 master.mp4 / 已存在 / 与视觉相同都被拒绝。
        using var paths = Env.Create([Seg(1, 24000, 1, 24000, 0, 2000)]);
        var wrongName = paths.Request() with { OutputPath = Path.Combine(paths.Work, "other.mp4") };
        await Check.ThrowsAsync(
            () => new FixedFfmpegMasterVideoComposer(paths.Runner).ComposeAsync(wrongName, CancellationToken.None),
            MasterVideoComposerException.RequestInvalid,
            "输出文件名固定为 master.mp4").ConfigureAwait(false);
        File.WriteAllText(paths.OutputPath, "pre-existing");
        await Check.ThrowsAsync(
            () => new FixedFfmpegMasterVideoComposer(paths.Runner).ComposeAsync(paths.Request(), CancellationToken.None),
            MasterVideoComposerException.RequestInvalid,
            "已存在的输出必须拒绝").ConfigureAwait(false);
        Check.Equal("pre-existing", File.ReadAllText(paths.OutputPath), "请求无效时不得动现有文件");
    }

    // ── 精确窗口 ──────────────────────────────────────────────────────────────────────────
    private static async Task ExactWindowAsync()
    {
        // 恰好填满窗口：48000 帧 @48 kHz == 1000 ms。
        using var exact = Env.Create([Seg(1, 48000, 1, 48000, 0, 1000)]);
        await new FixedFfmpegMasterVideoComposer(exact.Runner).ComposeAsync(exact.Request(), CancellationToken.None)
            .ConfigureAwait(false);
        Check.True(File.Exists(exact.OutputPath), "精确窗口允许");

        // 多一个样本帧即拒绝，且不启动进程。
        using var over = Env.Create([Seg(1, 48000, 1, 48001, 0, 1000)]);
        await Check.ThrowsAsync(
            () => new FixedFfmpegMasterVideoComposer(over.Runner).ComposeAsync(over.Request(), CancellationToken.None),
            MasterVideoComposerException.SegmentTooLong,
            "超过窗口一个样本帧必须拒绝").ConfigureAwait(false);
        Check.Equal(0, over.Runner.Calls.Count, "超窗不得启动进程");
    }

    // ── 图与参数策略 ───────────────────────────────────────────────────────────────────────
    private static void GraphAndArgumentPolicy()
    {
        using var env = Env.Create(
            [Seg(1, 24000, 1, 24000, 0, 2500), Seg(2, 44100, 2, 44100, 2500, 5000), Seg(3, 48000, 1, 48000, 5000, 6000)]);
        var filter = FixedFfmpegMasterVideoComposer.BuildFilterComplex(env.Segments, Target);
        const string stereoPan = "pan=mono|c0=0.5*c0+0.5*c1";
        Check.Equal(1, Regex.Matches(filter, Regex.Escape(stereoPan)).Count, "仅立体声片段使用显式 0.5/0.5 pan");
        Check.True(filter.Contains($"[2:a]{stereoPan},aformat", StringComparison.Ordinal), "pan 位于立体声输入之后");
        Check.True(!filter.Contains("[1:a]pan", StringComparison.Ordinal) && !filter.Contains("[3:a]pan", StringComparison.Ordinal),
            "单声道不得有隐式或显式声道策略");
        Check.True(filter.Contains("adelay=0:all=1[a0]", StringComparison.Ordinal), "精确 StartMs 延迟 0");
        Check.True(filter.Contains("adelay=2500:all=1[a1]", StringComparison.Ordinal), "精确 StartMs 延迟 2500");
        Check.True(filter.Contains("adelay=5000:all=1[a2]", StringComparison.Ordinal), "精确 StartMs 延迟 5000");
        Check.True(filter.EndsWith("[a0][a1][a2]amix=inputs=3:duration=longest:normalize=0,apad=whole_dur=6.000[aout]", StringComparison.Ordinal),
            "固定 amix + apad 尾部");
        foreach (var forbidden in new[] { "atempo", "atrim", "scale", "fps=", "format=pix", "setpts", "trim=" })
        {
            Check.True(!filter.Contains(forbidden, StringComparison.Ordinal), $"滤镜图不得含 {forbidden}");
        }
        // 滤镜文本只由整数时间与固定结构构成。
        var skeleton = Regex.Replace(filter, @"\d+", "N");
        Check.True(
            Regex.IsMatch(skeleton, @"^(\[N:a\](pan=mono\|c0=N\.N\*c0\+N\.N\*c1,)?aformat=sample_rates=N:channel_layouts=mono:sample_fmts=fltp,adelay=N:all=1\[aN\];)+(\[aN\])+amix=inputs=N:duration=longest:normalize=N,apad=whole_dur=N\.N\[aout\]$"),
            "滤镜图只含固定结构 + 整数");

        var args = FixedFfmpegMasterVideoComposer.BuildMuxArguments(env.Visual.Path, env.Segments, Target, env.OutputPath);
        Check.True(ContainsPair(args, "-c:v", "copy"), "必须恰有 -c:v copy");
        Check.Equal(1, args.Count(argument => argument == "-c:v"), "只有一个 -c:v");
        Check.True(ContainsPair(args, "-c:a", "aac") && ContainsPair(args, "-profile:a", "aac_low")
            && ContainsPair(args, "-b:a", "128k") && ContainsPair(args, "-ar", "48000") && ContainsPair(args, "-ac", "1"),
            "AAC-LC/48k/单声道/128k");
        Check.True(ContainsPair(args, "-map", "0:v:0") && ContainsPair(args, "-map", "[aout]"), "固定映射");
        Check.True(args.Contains("+faststart") && args.Contains("-nostdin") && args.Contains("-map_metadata"), "固定 mp4 参数");
        foreach (var forbidden in new[] { "libx264", "nvenc", "libx265", "-vf", "-filter:v", "-pix_fmt", "-r", "-s", "-shortest", "-vcodec", "atempo", "atrim" })
        {
            Check.True(!args.Contains(forbidden), $"参数不得含 {forbidden}");
        }
        // 输入顺序：视觉在前，WAV 按 Order。
        var inputs = args.Select((value, index) => (value, index)).Where(item => item.value == "-i")
            .Select(item => args[item.index + 1]).ToList();
        Check.Equal(4, inputs.Count, "1 视觉 + 3 WAV");
        Check.Equal(env.Visual.Path, inputs[0], "input 0 是视觉");
        Check.True(inputs.Skip(1).SequenceEqual(env.Segments.Select(segment => segment.WavPath)), "WAV 按 Order");

        // 单声道-only 图不含任何 pan。
        using var mono = Env.Create([Seg(1, 48000, 1, 48000, 0, 1000)]);
        Check.True(!FixedFfmpegMasterVideoComposer.BuildFilterComplex(mono.Segments, Target).Contains("pan=", StringComparison.Ordinal),
            "mono 图无 pan");
    }

    private static bool ContainsPair(IReadOnlyList<string> args, string key, string value)
    {
        for (var index = 0; index + 1 < args.Count; index++)
        {
            if (args[index] == key && args[index + 1] == value)
            {
                return true;
            }
        }
        return false;
    }

    // ── ffprobe 校验 ──────────────────────────────────────────────────────────────────────
    private static async Task ProbeValidationAsync()
    {
        // 输入有音频 / 多余流 / 错误编码 / 像素格式 / 时长不符 → 拒绝且不 mux。
        var badInputs = new (string Name, string Json)[]
        {
            ("input-has-audio", FakeRunner.Json(video: true, audio: ("aac", "LC", 48000, 1))),
            ("input-extra-stream", FakeRunner.Json(video: true, extra: 1)),
            ("input-wrong-codec", FakeRunner.Json(video: true, videoCodec: "hevc")),
            ("input-wrong-pixfmt", FakeRunner.Json(video: true, pixFmt: "yuv444p")),
            ("input-duration-mismatch", FakeRunner.Json(video: true, duration: "9.000000")),
            ("input-malformed", "{\"streams\": 7}"),
        };
        foreach (var (name, json) in badInputs)
        {
            using var env = Env.Create([Seg(1, 24000, 1, 24000, 0, 2000)]);
            env.Runner.InputProbe = json;
            var expected = name == "input-malformed" ? MasterVideoComposerException.ProbeInvalid : MasterVideoComposerException.VisualInvalid;
            await Check.ThrowsAsync(
                () => new FixedFfmpegMasterVideoComposer(env.Runner).ComposeAsync(env.Request(), CancellationToken.None),
                expected,
                $"{name} 必须拒绝").ConfigureAwait(false);
            Check.True(env.Runner.Calls.All(call => call.FileName == "ffprobe.exe"), $"{name} 不得进入 ffmpeg");
            Check.True(!File.Exists(env.OutputPath), $"{name} 不得写输出");
        }

        // 输出各项偏差 → OutputInvalid 且输出被删除。
        var badOutputs = new (string Name, string Json)[]
        {
            ("no-audio", FakeRunner.Json(video: true)),
            ("wrong-profile", FakeRunner.Json(video: true, audio: ("aac", "HE-AAC", 48000, 1))),
            ("wrong-rate", FakeRunner.Json(video: true, audio: ("aac", "LC", 44100, 1))),
            ("stereo", FakeRunner.Json(video: true, audio: ("aac", "LC", 48000, 2))),
            ("wrong-codec", FakeRunner.Json(video: true, audio: ("mp3", "LC", 48000, 1))),
            ("packet-count", FakeRunner.Json(video: true, audio: ("aac", "LC", 48000, 1), packets: 143)),
            ("fps", FakeRunner.Json(video: true, audio: ("aac", "LC", 48000, 1), fps: "25/1")),
            ("size", FakeRunner.Json(video: true, audio: ("aac", "LC", 48000, 1), width: 640)),
            ("extra-stream", FakeRunner.Json(video: true, audio: ("aac", "LC", 48000, 1), extra: 1)),
            ("duration", FakeRunner.Json(video: true, audio: ("aac", "LC", 48000, 1), duration: "6.500000")),
        };
        foreach (var (name, json) in badOutputs)
        {
            using var env = Env.Create([Seg(1, 24000, 1, 24000, 0, 2000)]);
            env.Runner.OutputProbe = json;
            await Check.ThrowsAsync(
                () => new FixedFfmpegMasterVideoComposer(env.Runner).ComposeAsync(env.Request(), CancellationToken.None),
                MasterVideoComposerException.OutputInvalid,
                $"输出 {name} 必须拒绝").ConfigureAwait(false);
            Check.True(!File.Exists(env.OutputPath), $"输出 {name} 后必须删除输出");
        }

        // 正常路径：先 ffprobe 输入，再 ffmpeg，最后 ffprobe 输出；ffmpeg 恰好一次。
        using var good = Env.Create([Seg(1, 24000, 1, 24000, 0, 2000)]);
        await new FixedFfmpegMasterVideoComposer(good.Runner).ComposeAsync(good.Request(), CancellationToken.None)
            .ConfigureAwait(false);
        Check.Equal("ffprobe.exe,ffmpeg.exe,ffprobe.exe", string.Join(',', good.Runner.Calls.Select(call => call.FileName)), "进程调用顺序");
        Check.True(File.Exists(good.OutputPath), "成功后输出存在");
    }

    // ── 超时 / 取消 / 失败：删除部分输出，错误有界 ───────────────────────────────────────────
    private static async Task TimeoutCancelAndErrorsAsync()
    {
        using var timeout = Env.Create([Seg(1, 24000, 1, 24000, 0, 2000)]);
        timeout.Runner.Mode = FakeMode.Timeout;
        await Check.ThrowsAsync(
            () => new FixedFfmpegMasterVideoComposer(timeout.Runner).ComposeAsync(timeout.Request(), CancellationToken.None),
            MasterVideoComposerException.FfmpegTimeout,
            "超时有界").ConfigureAwait(false);
        Check.True(!File.Exists(timeout.OutputPath), "超时后必须删除部分输出");

        using var cancel = Env.Create([Seg(1, 24000, 1, 24000, 0, 2000)]);
        cancel.Runner.Mode = FakeMode.Cancel;
        try
        {
            await new FixedFfmpegMasterVideoComposer(cancel.Runner).ComposeAsync(cancel.Request(), CancellationToken.None)
                .ConfigureAwait(false);
            throw new InvalidOperationException("取消必须抛出");
        }
        catch (OperationCanceledException)
        {
            // 预期。
        }
        Check.True(!File.Exists(cancel.OutputPath), "取消后必须删除部分输出");

        using var fail = Env.Create([Seg(1, 24000, 1, 24000, 0, 2000)]);
        fail.Runner.Mode = FakeMode.ExitFailure;
        var failure = await Check.ThrowsAsync(
            () => new FixedFfmpegMasterVideoComposer(fail.Runner).ComposeAsync(fail.Request(), CancellationToken.None),
            MasterVideoComposerException.FfmpegFailed,
            "ffmpeg 失败有界").ConfigureAwait(false);
        Check.Equal(MasterVideoComposerException.FfmpegFailed, failure.Message, "错误消息只是封闭码");
        Check.True(!failure.Message.Contains("SECRET", StringComparison.Ordinal)
            && !failure.Message.Contains(fail.Work, StringComparison.OrdinalIgnoreCase), "stderr/路径不得外泄");
        Check.True(!File.Exists(fail.OutputPath), "失败后必须删除部分输出");
        Check.True(File.Exists(fail.Visual.Path) && File.Exists(fail.Segments[0].WavPath), "来源文件绝不被删除");
    }

    // ── 可执行文件策略：不会启动任何进程 ─────────────────────────────────────────────────────
    private static async Task ExecutablePolicyAsync()
    {
        var runner = new FixedMasterVideoProcessRunner();
        foreach (var name in new[] { "cmd.exe", "powershell.exe", "ffmpeg.exe.bat", "C:\\tools\\ffmpeg.exe" })
        {
            await Check.ThrowsAsync(
                () => runner.RunAsync(new ProcessStartInfo { FileName = name }, TimeSpan.FromSeconds(1), CancellationToken.None),
                MasterVideoComposerException.FfmpegUnavailable,
                $"{name} 必须被拒绝").ConfigureAwait(false);
        }
        await Check.ThrowsAsync(
            () => runner.RunAsync(
                new ProcessStartInfo { FileName = "ffmpeg.exe", UseShellExecute = true }, TimeSpan.FromSeconds(1), CancellationToken.None),
            MasterVideoComposerException.FfmpegUnavailable,
            "UseShellExecute 必须被拒绝").ConfigureAwait(false);
    }

    private static SegSpec Seg(int order, int rate, int channels, long frames, long startMs, long endMs) =>
        new(order, rate, channels, frames, startMs, endMs);
}

internal sealed record SegSpec(int Order, int Rate, int Channels, long Frames, long StartMs, long EndMs);

internal enum FakeMode
{
    Normal,
    Timeout,
    Cancel,
    ExitFailure,
}

/// <summary>假 ffmpeg/ffprobe：记录调用，按路径返回受控 ffprobe JSON，按模式产出/破坏输出。</summary>
internal sealed class FakeRunner : IMasterVideoProcessRunner
{
    public List<(string FileName, List<string> Arguments)> Calls { get; } = [];

    public FakeMode Mode { get; set; }

    public string? InputProbe { get; set; }

    public string? OutputProbe { get; set; }

    public Task<MasterVideoProcessResult> RunAsync(
        ProcessStartInfo startInfo,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var arguments = startInfo.ArgumentList.ToList();
        Calls.Add((startInfo.FileName, arguments));
        if (startInfo.FileName == "ffprobe.exe")
        {
            var isOutput = Path.GetFileName(arguments[^1]) == "master.mp4";
            var json = isOutput
                ? OutputProbe ?? Json(video: true, audio: ("aac", "LC", 48000, 1))
                : InputProbe ?? Json(video: true);
            return Task.FromResult(new MasterVideoProcessResult(0, false, json));
        }

        var output = arguments[^1];
        switch (Mode)
        {
            case FakeMode.Timeout:
                File.WriteAllBytes(output, [1, 2, 3]);
                return Task.FromResult(new MasterVideoProcessResult(-1, true, string.Empty));
            case FakeMode.Cancel:
                File.WriteAllBytes(output, [1, 2, 3]);
                throw new OperationCanceledException(cancellationToken);
            case FakeMode.ExitFailure:
                File.WriteAllBytes(output, [1, 2, 3]);
                return Task.FromResult(new MasterVideoProcessResult(1, false, "SECRET-STDERR " + output));
        }
        File.WriteAllBytes(output, Encoding.ASCII.GetBytes("FAKE-MASTER-" + Guid.NewGuid().ToString("N")));
        return Task.FromResult(new MasterVideoProcessResult(0, false, string.Empty));
    }

    public static string Json(
        bool video,
        (string Codec, string Profile, int Rate, int Channels)? audio = null,
        int extra = 0,
        string videoCodec = "h264",
        string pixFmt = "yuv420p",
        string fps = "24/1",
        int width = 832,
        int height = 480,
        int packets = 144,
        string duration = "6.000000")
    {
        var streams = new List<string>();
        if (video)
        {
            streams.Add(
                $"{{\"codec_name\":\"{videoCodec}\",\"codec_type\":\"video\",\"width\":{width},\"height\":{height},"
                + $"\"pix_fmt\":\"{pixFmt}\",\"r_frame_rate\":\"{fps}\",\"nb_read_packets\":\"{packets}\"}}");
        }
        if (audio is { } a)
        {
            streams.Add(
                $"{{\"codec_name\":\"{a.Codec}\",\"profile\":\"{a.Profile}\",\"codec_type\":\"audio\","
                + $"\"sample_rate\":\"{a.Rate}\",\"channels\":{a.Channels},\"nb_read_packets\":\"280\"}}");
        }
        for (var index = 0; index < extra; index++)
        {
            streams.Add("{\"codec_type\":\"subtitle\",\"codec_name\":\"mov_text\",\"nb_read_packets\":\"1\"}");
        }
        return "{\"streams\":[" + string.Join(',', streams) + "],\"format\":{\"duration\":\"" + duration + "\"}}";
    }
}

internal sealed class TestEnv : IDisposable
{
    private readonly string _root;

    public TestEnv(string root, FakeRunner runner, VerifiedMasterVisual visual, byte[] visualBytes,
        IReadOnlyList<VerifiedMasterNarrationSegment> segments, string work)
    {
        _root = root;
        Runner = runner;
        Visual = visual;
        VisualBytes = visualBytes;
        Segments = segments;
        Work = work;
    }

    public FakeRunner Runner { get; }
    public VerifiedMasterVisual Visual { get; }
    public byte[] VisualBytes { get; }
    public IReadOnlyList<VerifiedMasterNarrationSegment> Segments { get; }
    public string Work { get; }
    public string OutputPath => Path.Combine(Work, "master.mp4");

    public MasterVideoCompositionRequest Request(IReadOnlyList<VerifiedMasterNarrationSegment>? segments = null) =>
        new(Visual, segments ?? Segments, 6000, OutputPath);

    public void Dispose()
    {
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, recursive: true);
        }
    }
}

internal static class Env
{
    public static TestEnv Create(IReadOnlyList<SegSpec> specs)
    {
        var root = Path.Combine(Path.GetTempPath(), "picotoo-mux-smoke-" + Guid.NewGuid().ToString("N"));
        var sources = Path.Combine(root, "sources");
        var work = Path.Combine(root, "work");
        Directory.CreateDirectory(sources);
        Directory.CreateDirectory(work);
        var visualBytes = Encoding.ASCII.GetBytes("FAKE-H264-MP4-VISUAL-" + Guid.NewGuid().ToString("N"));
        var visualPath = Path.Combine(sources, "visual.mp4");
        File.WriteAllBytes(visualPath, visualBytes);
        var visual = new VerifiedMasterVisual(visualPath, TestMedia.Sha(visualBytes), visualBytes.LongLength, "c004");
        var segments = specs
            .Select(spec => TestMedia.Segment(sources, spec.Order, spec.Rate, spec.Channels, spec.Frames, spec.StartMs, spec.EndMs, 440 * spec.Order))
            .ToList();
        return new TestEnv(root, new FakeRunner(), visual, visualBytes, segments, work);
    }
}
