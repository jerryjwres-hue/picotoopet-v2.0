using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.CaptionOverlay.SmokeTests;

/// <summary>渲染器 + 产物：假 ffmpeg/ffprobe 进程边界，真实文件系统与真实服务逻辑。</summary>
internal static class RendererAndArtifactTests
{
    private const string Job = "job-1";
    private const string English = "Fresh & Fast 'dry' 100%";
    private const string Chinese = "快速干燥，轻松护理";

    public static async Task RunAsync()
    {
        var workspace = Path.Combine(Path.GetTempPath(), "picotoo-overlay-smoke-" + Guid.NewGuid().ToString("N"));
        try
        {
            await VerifyFilterChainAsync().ConfigureAwait(false);
            await VerifySourceVerificationAsync(workspace).ConfigureAwait(false);
            await VerifyRenderAndArtifactLifecycleAsync(workspace).ConfigureAwait(false);
            await VerifyFailureCleanupAsync(workspace).ConfigureAwait(false);
        }
        finally
        {
            if (Directory.Exists(workspace))
            {
                Directory.Delete(workspace, recursive: true);
            }
        }
    }

    private static Task VerifyFilterChainAsync()
    {
        var fonts = Fixture.CreateFonts(Path.Combine(Path.GetTempPath(), "picotoo-fonts-" + Guid.NewGuid().ToString("N")));
        try
        {
            var plan = Fixture.Plan(("c1", English, 500, 2500), ("c2", Chinese, 3000, 5500));
            var cues = WindowsCaptionOverlayRenderer.PrepareCues(plan.Plan, new WindowsTextOverlayFontPolicy(fonts));
            SmokeAssert.Equal("arial.ttf", cues[0].Font.FileName, "英文 cue 使用英文策略");
            SmokeAssert.Equal("msyh.ttc", cues[1].Font.FileName, "中文 cue 使用中文策略");

            var layout = WindowsCaptionOverlayRenderer.LayoutFor(plan.Plan.OutputProfileId);
            var chain = WindowsCaptionOverlayRenderer.BuildFilterChain(
                layout,
                [(cues[0], "font_01.ttf", "cue_001.txt"), (cues[1], "font_02.ttc", "cue_002.txt")]);
            const string expected =
                "drawtext=fontfile=font_01.ttf:textfile=cue_001.txt:expansion=none:fontsize=34:fontcolor=white"
                + ":box=1:boxcolor=black@0.5:boxborderw=12:x=(w-text_w)/2:y=h*0.78:enable='gte(t,0.500)*lt(t,2.500)',"
                + "drawtext=fontfile=font_02.ttc:textfile=cue_002.txt:expansion=none:fontsize=34:fontcolor=white"
                + ":box=1:boxcolor=black@0.5:boxborderw=12:x=(w-text_w)/2:y=h*0.78:enable='gte(t,3.000)*lt(t,5.500)'";
            SmokeAssert.Equal(expected, chain, "精确 drawtext 链与整数毫秒时间窗");
            SmokeAssert.True(!chain.Contains("Fresh", StringComparison.Ordinal), "滤镜串不得含文案（英文）");
            SmokeAssert.True(!chain.Contains("快", StringComparison.Ordinal), "滤镜串不得含文案（中文）");
            SmokeAssert.True(!chain.Contains('\\') && !chain.Contains(":/", StringComparison.Ordinal), "滤镜串不含路径或盘符");

            // 版式只由闭集档位决定。
            SmokeAssert.Equal(30, WindowsCaptionOverlayRenderer.LayoutFor("video.square.v1").FontSize, "square 字号");
            SmokeAssert.Equal(28, WindowsCaptionOverlayRenderer.LayoutFor("video.vertical.v1").FontSize, "vertical 字号");

            // 无效/重叠倒序/越界/超宽/控制字符 cue 在到达 FFmpeg 之前被拒绝。
            foreach (var bad in new[]
            {
                Fixture.Plan(("c1", English, 3000, 4000), ("c2", English, 500, 1000)),
                Fixture.Plan(("c1", new string('W', 120), 500, 1000)),
                Fixture.Plan(("c1", "line1\nline2", 500, 1000)),
            })
            {
                try
                {
                    WindowsCaptionOverlayRenderer.PrepareCues(bad.Plan, new WindowsTextOverlayFontPolicy(fonts));
                    throw new InvalidOperationException("无效 cue 必须拒绝");
                }
                catch (TextOverlayException exception)
                {
                    SmokeAssert.Equal(TextOverlayException.PlanInvalid, exception.Code, "无效 cue 错误码");
                }
            }
        }
        finally
        {
            Directory.Delete(fonts, recursive: true);
        }
        return Task.CompletedTask;
    }

    private static async Task VerifySourceVerificationAsync(string workspace)
    {
        var env = Fixture.Create(workspace, "src-verify");
        var plan = Fixture.Plan(("c1", English, 500, 2500));
        var outside = Path.Combine(workspace, "src-verify", "elsewhere.mp4");
        await File.WriteAllBytesAsync(outside, env.SourceBytes).ConfigureAwait(false);

        // 托管根之外的文件即使字节一致也不是权威源。
        await SmokeAssert.ThrowsCodeAsync(
            () => env.Service.ApplyAsync(env.Source with { FilePath = outside }, plan, CancellationToken.None),
            TextOverlayException.SourceInvalid,
            "托管根外的源必须拒绝").ConfigureAwait(false);

        // job 不匹配。
        await SmokeAssert.ThrowsCodeAsync(
            () => env.Service.ApplyAsync(env.Source with { ProductionJobId = "other-job" }, plan, CancellationToken.None),
            TextOverlayException.SourceInvalid,
            "plan/source job 不匹配必须拒绝").ConfigureAwait(false);

        // 记录的字节数/SHA 不一致。
        await SmokeAssert.ThrowsCodeAsync(
            () => env.Service.ApplyAsync(env.Source with { Bytes = env.Source.Bytes + 1 }, plan, CancellationToken.None),
            TextOverlayException.SourceInvalid,
            "字节数不一致必须拒绝").ConfigureAwait(false);
        await SmokeAssert.ThrowsCodeAsync(
            () => env.Service.ApplyAsync(env.Source with { Sha256 = new string('a', 64) }, plan, CancellationToken.None),
            TextOverlayException.SourceInvalid,
            "SHA 不一致必须拒绝").ConfigureAwait(false);

        // 磁盘上被篡改的源（长度相同、内容不同）→ 重新计算 SHA 后拒绝。
        var tampered = (byte[])env.SourceBytes.Clone();
        tampered[0] ^= 0xFF;
        await File.WriteAllBytesAsync(env.Source.FilePath, tampered).ConfigureAwait(false);
        await SmokeAssert.ThrowsCodeAsync(
            () => env.Service.ApplyAsync(env.Source, plan, CancellationToken.None),
            TextOverlayException.SourceInvalid,
            "被篡改的源必须拒绝").ConfigureAwait(false);
        SmokeAssert.Equal(0, env.Runner.Calls.Count, "源无效时不得调用任何进程");
    }

    private static async Task VerifyRenderAndArtifactLifecycleAsync(string workspace)
    {
        var env = Fixture.Create(workspace, "lifecycle");

        // 空计划：直通，不调用 ffmpeg，不复制。
        var empty = Fixture.Plan();
        var passthrough = await env.Service.ApplyAsync(env.Source, empty, CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(passthrough.Passthrough, "空计划必须 passthrough");
        SmokeAssert.Equal(env.Source.Sha256, passthrough.Sha256, "直通引用 C004 源");
        SmokeAssert.Equal(0, env.Runner.Calls.Count, "空计划不得调用 ffmpeg");
        SmokeAssert.True(!Directory.Exists(env.OverlayRoot) || Directory.GetFileSystemEntries(env.OverlayRoot).Length == 0, "空计划不得写出任何产物");

        // 英文 + 中文多 cue 顺序渲染。
        var plan = Fixture.Plan(("c1", English, 500, 2500), ("c2", Chinese, 3000, 5500));
        var first = await env.Service.ApplyAsync(env.Source, plan, CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(!first.Reused && !first.Passthrough, "首次渲染不是复用");
        SmokeAssert.True(File.Exists(first.FilePath) && File.Exists(first.ManifestPath!), "产物与清单必须存在");
        SmokeAssert.True(
            first.FilePath.StartsWith(Path.GetFullPath(env.OverlayRoot) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase),
            "输出只在托管根内");
        SmokeAssert.Equal(
            Convert.ToHexString(SHA256.HashData(await File.ReadAllBytesAsync(first.FilePath).ConfigureAwait(false))).ToLowerInvariant(),
            first.Sha256,
            "输出 SHA 与磁盘一致");

        // 假 ffmpeg 看到的是：UTF-8 textfile 内容、复制的字体、固定参数、无 shell。
        var render = env.Runner.Calls.Single(call => call.FileName == "ffmpeg.exe");
        SmokeAssert.Equal(English, render.TextFiles["cue_001.txt"], "英文 cue 文件内容原样（含 %、&、'）");
        SmokeAssert.Equal(Chinese, render.TextFiles["cue_002.txt"], "中文 cue 文件 UTF-8 原样");
        SmokeAssert.Equal(2, render.FontFiles.Count, "两种字体身份各复制一次");
        SmokeAssert.True(!render.Arguments.Any(arg => arg.Contains("Fresh", StringComparison.Ordinal) || arg.Contains("快", StringComparison.Ordinal)), "文案不得出现在任何命令行参数里");
        SmokeAssert.True(!render.UseShellExecute, "不得使用 shell");
        foreach (var flag in new[] { "-nostdin", "-an", "libx264", "yuv420p", "+faststart", "+bitexact" })
        {
            SmokeAssert.True(render.Arguments.Contains(flag), $"固定参数缺失 {flag}");
        }

        // 清单：无文案、无绝对路径；含身份与 cue 摘要。
        var manifestText = await File.ReadAllTextAsync(first.ManifestPath!).ConfigureAwait(false);
        SmokeAssert.True(!manifestText.Contains("Fresh", StringComparison.Ordinal), "清单不含文案（英文）");
        SmokeAssert.True(!manifestText.Contains("快速", StringComparison.Ordinal), "清单不含文案（中文）");
        SmokeAssert.True(!manifestText.Contains(workspace, StringComparison.OrdinalIgnoreCase), "清单不含绝对路径");
        SmokeAssert.True(!manifestText.Contains(":\\", StringComparison.Ordinal), "清单不含盘符路径");
        foreach (var token in new[] { "text_sha256", "resolved_font_identity_sha256", "artifact_identity_sha256", "source_final_sha256", "caption_overlay_plan_digest", "output_sha256" })
        {
            SmokeAssert.True(manifestText.Contains(token, StringComparison.Ordinal), $"清单缺字段 {token}");
        }

        // 同源 + 同计划 + 同字体身份 → 复用；不再调用 ffmpeg。
        var callsBefore = env.Runner.Calls.Count;
        var reused = await env.Service.ApplyAsync(env.Source, plan, CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(reused.Reused, "相同输入必须复用");
        SmokeAssert.Equal(first.Sha256, reused.Sha256, "复用同一输出");
        SmokeAssert.Equal(callsBefore, env.Runner.Calls.Count, "复用不得再次渲染");

        // 计划 digest 变化 → 不复用，生成不同产物。
        var changed = plan with { CaptionOverlayPlanDigest = new string('c', 64) };
        var other = await env.Service.ApplyAsync(env.Source, changed, CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(!other.Reused, "digest 变化不得复用");
        SmokeAssert.True(!string.Equals(other.FilePath, first.FilePath, StringComparison.OrdinalIgnoreCase), "不同身份不同文件");

        // 输出被篡改 → fail closed，且不被覆盖。
        var original = await File.ReadAllBytesAsync(first.FilePath).ConfigureAwait(false);
        var tampered = (byte[])original.Clone();
        tampered[^1] ^= 0xFF;
        await File.WriteAllBytesAsync(first.FilePath, tampered).ConfigureAwait(false);
        await SmokeAssert.ThrowsCodeAsync(
            () => env.Service.ApplyAsync(env.Source, plan, CancellationToken.None),
            TextOverlayException.ArtifactConflict,
            "被篡改的输出必须 fail closed").ConfigureAwait(false);
        SmokeAssert.True(
            (await File.ReadAllBytesAsync(first.FilePath).ConfigureAwait(false)).AsSpan().SequenceEqual(tampered),
            "冲突输出不得被静默覆盖");

        // 部分产物（输出存在、清单缺失）→ fail closed。
        await File.WriteAllBytesAsync(first.FilePath, original).ConfigureAwait(false);
        File.Delete(first.ManifestPath!);
        await SmokeAssert.ThrowsCodeAsync(
            () => env.Service.ApplyAsync(env.Source, plan, CancellationToken.None),
            TextOverlayException.ArtifactConflict,
            "缺清单的部分产物必须 fail closed").ConfigureAwait(false);

        // 字体身份变化 → 身份变化 → 不复用旧产物。
        var swapped = Fixture.Create(workspace, "lifecycle-font-swap", differentFontBytes: true);
        var swappedArtifact = await swapped.Service.ApplyAsync(swapped.Source, plan, CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(
            !string.Equals(Path.GetFileName(swappedArtifact.FilePath), Path.GetFileName(first.FilePath), StringComparison.OrdinalIgnoreCase),
            "字体身份进入产物身份");
    }

    private static async Task VerifyFailureCleanupAsync(string workspace)
    {
        var plan = Fixture.Plan(("c1", English, 500, 2500));

        var timeoutEnv = Fixture.Create(workspace, "timeout");
        timeoutEnv.Runner.Mode = FakeRunnerMode.Timeout;
        await SmokeAssert.ThrowsCodeAsync(
            () => timeoutEnv.Service.ApplyAsync(timeoutEnv.Source, plan, CancellationToken.None),
            TextOverlayException.FfmpegTimeout,
            "超时必须是有界 FFMPEG_TIMEOUT").ConfigureAwait(false);
        AssertNoResidue(timeoutEnv.OverlayRoot, "超时");

        var cancelEnv = Fixture.Create(workspace, "cancel");
        cancelEnv.Runner.Mode = FakeRunnerMode.Cancel;
        try
        {
            await cancelEnv.Service.ApplyAsync(cancelEnv.Source, plan, CancellationToken.None).ConfigureAwait(false);
            throw new InvalidOperationException("取消必须抛出");
        }
        catch (OperationCanceledException)
        {
            // 取消沿调用栈传播。
        }
        AssertNoResidue(cancelEnv.OverlayRoot, "取消");

        var failEnv = Fixture.Create(workspace, "fail");
        failEnv.Runner.Mode = FakeRunnerMode.ExitFailure;
        var failure = await SmokeAssert.ThrowsCodeAsync(
            () => failEnv.Service.ApplyAsync(failEnv.Source, plan, CancellationToken.None),
            TextOverlayException.FfmpegFailed,
            "ffmpeg 失败必须是 FFMPEG_FAILED").ConfigureAwait(false);
        SmokeAssert.True(!failure.Message.Contains("Fresh", StringComparison.Ordinal), "错误不含文案");
        AssertNoResidue(failEnv.OverlayRoot, "失败");

        var badOutput = Fixture.Create(workspace, "bad-output");
        badOutput.Runner.Mode = FakeRunnerMode.WrongCodec;
        await SmokeAssert.ThrowsCodeAsync(
            () => badOutput.Service.ApplyAsync(badOutput.Source, plan, CancellationToken.None),
            TextOverlayException.OutputInvalid,
            "非 H.264 输出必须拒绝").ConfigureAwait(false);
        AssertNoResidue(badOutput.OverlayRoot, "无效输出");

        var missingFont = Fixture.Create(workspace, "no-font", omitFonts: true);
        await SmokeAssert.ThrowsCodeAsync(
            () => missingFont.Service.ApplyAsync(missingFont.Source, plan, CancellationToken.None),
            TextOverlayException.FontUnavailable,
            "缺字体必须有界失败").ConfigureAwait(false);
        SmokeAssert.Equal(0, missingFont.Runner.Calls.Count, "缺字体不得调用进程");
    }

    private static void AssertNoResidue(string overlayRoot, string scenario)
    {
        var entries = Directory.Exists(overlayRoot)
            ? Directory.GetFileSystemEntries(overlayRoot, "*", SearchOption.AllDirectories)
                .Where(path => !Directory.Exists(path) || Directory.GetFileSystemEntries(path).Length > 0)
                .ToArray()
            : [];
        SmokeAssert.Equal(0, entries.Length, $"{scenario}后托管根不得残留产物或临时文件");
    }
}

internal enum FakeRunnerMode
{
    Normal,
    Timeout,
    Cancel,
    ExitFailure,
    WrongCodec,
}

internal sealed record FakeCall(
    string FileName,
    IReadOnlyList<string> Arguments,
    bool UseShellExecute,
    IReadOnlyDictionary<string, string> TextFiles,
    IReadOnlyList<string> FontFiles);

/// <summary>假进程边界：模拟 ffprobe JSON 与 ffmpeg 输出文件，同时记录隔离工作目录里的输入。</summary>
internal sealed class FakeRunner : ITextOverlayProcessRunner
{
    public List<FakeCall> Calls { get; } = [];

    public FakeRunnerMode Mode { get; set; }

    public Task<TextOverlayProcessResult> RunAsync(
        ProcessStartInfo startInfo,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var workDirectory = startInfo.WorkingDirectory;
        var textFiles = new Dictionary<string, string>();
        var fontFiles = new List<string>();
        if (Directory.Exists(workDirectory))
        {
            foreach (var path in Directory.GetFiles(workDirectory))
            {
                var name = Path.GetFileName(path);
                if (name.StartsWith("cue_", StringComparison.Ordinal))
                {
                    textFiles[name] = File.ReadAllText(path, new UTF8Encoding(false));
                }
                else if (name.StartsWith("font_", StringComparison.Ordinal))
                {
                    fontFiles.Add(name);
                }
            }
        }
        Calls.Add(new FakeCall(
            startInfo.FileName,
            startInfo.ArgumentList.ToList(),
            startInfo.UseShellExecute,
            textFiles,
            fontFiles));

        if (startInfo.FileName == "ffprobe.exe")
        {
            var codec = Mode == FakeRunnerMode.WrongCodec && startInfo.ArgumentList.Last().EndsWith("render.mp4", StringComparison.Ordinal)
                ? "vp9"
                : "h264";
            return Task.FromResult(new TextOverlayProcessResult(
                0,
                false,
                "{\"streams\":[{\"codec_type\":\"video\",\"codec_name\":\"" + codec
                + "\",\"width\":832,\"height\":480,\"pix_fmt\":\"yuv420p\"}],\"format\":{\"duration\":\"6.000000\"}}"));
        }

        switch (Mode)
        {
            case FakeRunnerMode.Timeout:
                File.WriteAllBytes(Path.Combine(workDirectory, "render.mp4"), [1, 2, 3]);
                return Task.FromResult(new TextOverlayProcessResult(-1, true, string.Empty));
            case FakeRunnerMode.Cancel:
                File.WriteAllBytes(Path.Combine(workDirectory, "render.mp4"), [1, 2, 3]);
                throw new OperationCanceledException(cancellationToken);
            case FakeRunnerMode.ExitFailure:
                return Task.FromResult(new TextOverlayProcessResult(1, false, string.Empty));
        }
        File.WriteAllBytes(
            Path.Combine(workDirectory, "render.mp4"),
            Encoding.ASCII.GetBytes("FAKE-MP4-OUTPUT-" + Guid.NewGuid().ToString("N")));
        return Task.FromResult(new TextOverlayProcessResult(0, false, string.Empty));
    }
}

internal sealed record TestEnvironment(
    WindowsCaptionOverlayService Service,
    FakeRunner Runner,
    FinalVideoArtifact Source,
    byte[] SourceBytes,
    string OverlayRoot);

internal static class Fixture
{
    public static CaptionOverlayPlanResponseRecord Plan(params (string Id, string Text, int Start, int End)[] cues)
    {
        var overlays = cues.Select((cue, index) => new CaptionOverlayCueRecord(
            cue.Id,
            $"beat-{index + 1}",
            index + 1,
            "overlay",
            cue.Text,
            Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(cue.Text))).ToLowerInvariant(),
            cue.Start,
            cue.End)).ToList();
        return new CaptionOverlayPlanResponseRecord(
            new CaptionOverlayPlanRecord(
                "1.0",
                "job-1",
                "pkg-1",
                new string('a', 64),
                new string('b', 64),
                6000,
                "video.landscape.v1",
                CaptionOverlayConstants.CaptionStyleProfileId,
                CaptionOverlayConstants.OverlayStyleProfileId,
                CaptionOverlayConstants.FontProfileId,
                false,
                overlays.Count > 0,
                [],
                overlays),
            new string('d', 64));
    }

    public static string CreateFonts(string directory, bool differentBytes = false)
    {
        Directory.CreateDirectory(directory);
        var salt = differentBytes ? (byte)1 : (byte)0;
        var latin = WindowsSfntCmap.BuildFormat12Fixture((0x20, 0x7E));
        var cjk = WindowsSfntCmap.BuildFormat12Fixture((0x20, 0x7E), (0x3000, 0x9FFF), (0xFF00, 0xFFEF));
        File.WriteAllBytes(Path.Combine(directory, "arial.ttf"), [.. latin, salt]);
        File.WriteAllBytes(Path.Combine(directory, "msyh.ttc"), [.. cjk, salt]);
        return directory;
    }

    public static TestEnvironment Create(
        string workspace,
        string name,
        bool differentFontBytes = false,
        bool omitFonts = false)
    {
        var root = Path.Combine(workspace, name);
        var finalRoot = Path.Combine(root, "FinalVideos");
        var overlayRoot = Path.Combine(root, "TextOverlay", "v1");
        var fontsDirectory = Path.Combine(root, "Fonts");
        Directory.CreateDirectory(finalRoot);
        Directory.CreateDirectory(fontsDirectory);
        if (!omitFonts)
        {
            CreateFonts(fontsDirectory, differentFontBytes);
        }

        var identity = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(Plan().Plan.ProductionJobId)))
            .ToLowerInvariant()[..32];
        var path = Path.Combine(finalRoot, $"final-{identity}.mp4");
        var bytes = Encoding.ASCII.GetBytes("FAKE-C004-FINAL-VIDEO");
        File.WriteAllBytes(path, bytes);
        var source = new FinalVideoArtifact(
            "job-1",
            "package-1",
            new string('e', 64),
            path,
            Path.Combine(finalRoot, $"final-{identity}.final-video.json"),
            Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant(),
            bytes.LongLength,
            false);
        var runner = new FakeRunner();
        var service = new WindowsCaptionOverlayService(
            new WindowsCaptionOverlayRenderer(runner),
            new WindowsTextOverlayFontPolicy(fontsDirectory),
            finalRoot,
            overlayRoot,
            TimeProvider.System);
        return new TestEnvironment(service, runner, source, bytes, overlayRoot);
    }
}
