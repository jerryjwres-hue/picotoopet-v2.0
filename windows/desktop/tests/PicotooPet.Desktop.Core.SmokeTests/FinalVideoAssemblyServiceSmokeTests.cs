using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 Production Package 源校验、本地不可变复用与固定 FFmpeg 边界。</summary>
internal static class FinalVideoAssemblyServiceSmokeTests
{
    public static async Task RunAsync()
    {
        await PreservesOrderedVerifiedSourcesAndFixedFfmpegBoundaryAsync().ConfigureAwait(false);
        await RejectsUnsafeOrMismatchedSourcesAsync().ConfigureAwait(false);
        await RejectsReparseEscapeWhenSupportedAsync().ConfigureAwait(false);
        RejectsDirectoryReparseWhenSupported();
        await ReusesMatchingArtifactAndRejectsConflictAsync().ConfigureAwait(false);
        await MapsFfmpegFailureAndTimeoutToStableCodesAsync().ConfigureAwait(false);
    }

    private static async Task PreservesOrderedVerifiedSourcesAndFixedFfmpegBoundaryAsync()
    {
        using var fixture = new AssemblyFixture();
        var first = fixture.WriteSource("shots/001 first.webm", "first-shot");
        var second = fixture.WriteSource("shots/002-second.webm", "second-shot");
        var firstBefore = File.ReadAllBytes(first.Path);
        var secondBefore = File.ReadAllBytes(second.Path);
        var package = AssemblyFixture.Package(first.Output, second.Output);
        var process = new RecordingProcessRunner();
        var service = fixture.Service(package, new FixedFfmpegAssembler(process));

        var result = await service.AssembleAsync(package.ProductionJobId).ConfigureAwait(false);

        SmokeAssert.Equal("ffmpeg.exe", process.LastStartInfo?.FileName, "FFmpeg executable identity 可被外部输入改变");
        SmokeAssert.True(process.LastStartInfo is { UseShellExecute: false, CreateNoWindow: true }, "FFmpeg 未使用固定无 shell 进程边界");
        var arguments = process.LastStartInfo!.ArgumentList.ToArray();
        var inputArguments = arguments
            .Select((value, index) => (value, index))
            .Where(item => item.index > 0 && arguments[item.index - 1] == "-i")
            .Select(item => item.value)
            .ToArray();
        SmokeAssert.True(inputArguments.SequenceEqual([first.Path, second.Path]), "Production Package outputs 顺序未保留");
        SmokeAssert.True(arguments.Contains("libx264", StringComparer.Ordinal), "最终 MP4 未固定使用 H.264 编码");
        SmokeAssert.True(arguments.Contains("yuv420p", StringComparer.Ordinal), "最终 MP4 未固定普通 Windows 播放像素格式");
        SmokeAssert.True(result.FilePath.EndsWith(".mp4", StringComparison.OrdinalIgnoreCase), "最终成品不是 MP4");
        SmokeAssert.True(File.Exists(result.FilePath), "最终 MP4 未落入受管目录");
        SmokeAssert.True(File.Exists(result.ManifestPath), "最终视频有据 manifest 未落盘");
        SmokeAssert.True(File.ReadAllBytes(first.Path).SequenceEqual(firstBefore), "合成修改了第一个源 WebM");
        SmokeAssert.True(File.ReadAllBytes(second.Path).SequenceEqual(secondBefore), "合成修改了第二个源 WebM");
        var manifestText = File.ReadAllText(result.ManifestPath);
        SmokeAssert.True(!manifestText.Contains(fixture.OutputRoot, StringComparison.OrdinalIgnoreCase), "manifest 泄露源绝对路径");
        SmokeAssert.True(!manifestText.Contains(fixture.FinalRoot, StringComparison.OrdinalIgnoreCase), "manifest 泄露成品绝对路径");
    }

    private static async Task RejectsUnsafeOrMismatchedSourcesAsync()
    {
        using var fixture = new AssemblyFixture();
        var valid = fixture.WriteSource("shots/valid.webm", "valid-shot");
        var rooted = valid.Output with { OutputRelpath = valid.Path };
        var traversal = valid.Output with { OutputRelpath = "../outside.webm" };
        var missing = valid.Output with { OutputRelpath = "shots/missing.webm" };
        var mismatch = valid.Output with { OutputSha256 = new string('f', 64) };
        var invalidMime = valid.Output with { MimeType = "text/plain" };

        foreach (var output in new[] { rooted, traversal, missing, mismatch, invalidMime })
        {
            var ffmpeg = new RecordingFfmpeg();
            var package = AssemblyFixture.Package(output);
            await ExpectFailureAsync(() => fixture.Service(package, ffmpeg).AssembleAsync(package.ProductionJobId))
                .ConfigureAwait(false);
            SmokeAssert.Equal(0, ffmpeg.CallCount, "不安全或不匹配源仍进入 FFmpeg");
        }
    }

    private static async Task RejectsReparseEscapeWhenSupportedAsync()
    {
        using var fixture = new AssemblyFixture();
        var outside = Path.Combine(fixture.Root, "outside.webm");
        File.WriteAllText(outside, "outside-shot");
        var link = Path.Combine(fixture.OutputRoot, "shots", "linked.webm");
        Directory.CreateDirectory(Path.GetDirectoryName(link)!);
        try
        {
            File.CreateSymbolicLink(link, outside);
        }
        catch (Exception exception) when (exception is UnauthorizedAccessException or IOException or PlatformNotSupportedException)
        {
            return;
        }

        var output = AssemblyFixture.Output("shots/linked.webm", outside);
        var ffmpeg = new RecordingFfmpeg();
        await ExpectFailureAsync(() => fixture.Service(AssemblyFixture.Package(output), ffmpeg).AssembleAsync("job-1"))
            .ConfigureAwait(false);
        SmokeAssert.Equal(0, ffmpeg.CallCount, "reparse/symlink 源仍进入 FFmpeg");
    }

    private static void RejectsDirectoryReparseWhenSupported()
    {
        var root = Path.Combine(Path.GetTempPath(), $"picotoopet-final-root-link-{Guid.NewGuid():N}");
        var target = Path.Combine(Path.GetTempPath(), $"picotoopet-final-root-target-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        Directory.CreateDirectory(target);
        var link = Path.Combine(root, "final");
        try
        {
            try
            {
                Directory.CreateSymbolicLink(link, target);
            }
            catch (Exception exception) when (
                exception is UnauthorizedAccessException or IOException or PlatformNotSupportedException)
            {
                return;
            }

            var rejected = false;
            try
            {
                ProductionLocalEnvironment.AssertNoLinkEscape(link, link);
            }
            catch (InvalidDataException)
            {
                rejected = true;
            }
            SmokeAssert.True(rejected, "受管 FinalVideos 根目录为 reparse point 时未 fail closed");
        }
        finally
        {
            try
            {
                if (Directory.Exists(link))
                {
                    Directory.Delete(link);
                }
            }
            catch (IOException)
            {
            }
            Directory.Delete(root, recursive: true);
            Directory.Delete(target, recursive: true);
        }
    }

    private static async Task ReusesMatchingArtifactAndRejectsConflictAsync()
    {
        using var fixture = new AssemblyFixture();
        var source = fixture.WriteSource("shots/only.webm", "only-shot");
        var package = AssemblyFixture.Package(source.Output);
        var firstRunner = new RecordingFfmpeg();
        var first = await fixture.Service(package, firstRunner).AssembleAsync(package.ProductionJobId)
            .ConfigureAwait(false);
        SmokeAssert.Equal(1, firstRunner.CallCount, "首次合成未调用 FFmpeg");

        var reuseRunner = new RecordingFfmpeg { ThrowIfCalled = true };
        var reused = await fixture.Service(package, reuseRunner).AssembleAsync(package.ProductionJobId)
            .ConfigureAwait(false);
        SmokeAssert.True(reused.Reused, "重启后未复用匹配的本地成品");
        SmokeAssert.Equal(first.Sha256, reused.Sha256, "复用成品摘要变化");

        File.AppendAllText(reused.FilePath, "tampered");
        var conflictRunner = new RecordingFfmpeg { ThrowIfCalled = true };
        await ExpectFailureAsync(() => fixture.Service(package, conflictRunner).AssembleAsync(package.ProductionJobId))
            .ConfigureAwait(false);
        SmokeAssert.Equal(0, conflictRunner.CallCount, "冲突成品被覆盖或重新合成");
    }

    private static async Task MapsFfmpegFailureAndTimeoutToStableCodesAsync()
    {
        foreach (var result in new[]
        {
            new FinalVideoProcessResult(7, TimedOut: false),
            new FinalVideoProcessResult(null, TimedOut: true),
        })
        {
            var runner = new RecordingProcessRunner { Result = result };
            var assembler = new FixedFfmpegAssembler(runner);
            var failure = await CaptureFailureAsync(() => assembler.AssembleAsync(
                [@"C:\trusted\shot.webm"],
                @"C:\managed\final.mp4",
                832,
                480,
                24,
                CancellationToken.None)).ConfigureAwait(false);
            var expected = result.TimedOut ? "FINAL_VIDEO_FFMPEG_TIMEOUT" : "FINAL_VIDEO_FFMPEG_FAILED";
            SmokeAssert.Equal(expected, failure.Message, "FFmpeg 失败没有映射到稳定有界代码");
            SmokeAssert.True(!failure.Message.Contains("C:\\", StringComparison.Ordinal), "FFmpeg 失败泄露本地路径");
        }
    }

    private static async Task ExpectFailureAsync(Func<Task> action) =>
        _ = await CaptureFailureAsync(action).ConfigureAwait(false);

    private static async Task<Exception> CaptureFailureAsync(Func<Task> action)
    {
        try
        {
            await action().ConfigureAwait(false);
        }
        catch (Exception exception)
        {
            return exception;
        }
        throw new InvalidOperationException("预期操作失败但实际成功");
    }

    private sealed class AssemblyFixture : IDisposable
    {
        public AssemblyFixture()
        {
            Root = Path.Combine(Path.GetTempPath(), $"picotoopet-final-video-{Guid.NewGuid():N}");
            OutputRoot = Path.Combine(Root, "comfy-output");
            FinalRoot = Path.Combine(Root, "final");
            Directory.CreateDirectory(OutputRoot);
        }

        public string Root { get; }
        public string OutputRoot { get; }
        public string FinalRoot { get; }

        public (string Path, FinalVideoSourceOutput Output) WriteSource(string relative, string content)
        {
            var path = Path.GetFullPath(Path.Combine(OutputRoot, relative));
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, content);
            return (path, Output(relative, path));
        }

        public static FinalVideoSourceOutput Output(string relative, string actualPath) => new(
            relative,
            Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(actualPath))).ToLowerInvariant(),
            new FileInfo(actualPath).Length,
            "video/webm",
            832,
            480,
            81,
            24);

        public static ProductionPackageRecord Package(params FinalVideoSourceOutput[] outputs)
        {
            var manifest = JsonSerializer.SerializeToElement(new
            {
                schema_version = "1.0",
                production_package_id = "package-1",
                production_job_id = "job-1",
                outputs = outputs.Select(item => new
                {
                    output_relpath = item.OutputRelpath,
                    output_sha256 = item.OutputSha256,
                    output_bytes = item.OutputBytes,
                    mime_type = item.MimeType,
                    width = item.Width,
                    height = item.Height,
                    frame_count = item.FrameCount,
                    fps = item.Fps,
                }).ToArray(),
            });
            return new ProductionPackageRecord(
                "package-1",
                "job-1",
                "creative-package",
                new string('a', 64),
                new string('b', 64),
                "production/package-1.zip",
                manifest,
                "PASS",
                DateTimeOffset.UtcNow);
        }

        public FinalVideoAssemblyService Service(ProductionPackageRecord package, IFinalVideoFfmpeg ffmpeg) =>
            new(new FixturePackageGateway(package), ffmpeg, OutputRoot, FinalRoot, TimeProvider.System);

        public void Dispose()
        {
            if (Directory.Exists(Root))
            {
                Directory.Delete(Root, recursive: true);
            }
        }
    }

    private sealed class FixturePackageGateway(ProductionPackageRecord package) : IProductionPackageGateway
    {
        public Task<ProductionPackageRecord?> GetProductionPackageAsync(
            string productionJobId,
            CancellationToken cancellationToken) => Task.FromResult<ProductionPackageRecord?>(package);
    }

    private sealed class RecordingFfmpeg : IFinalVideoFfmpeg
    {
        public int CallCount { get; private set; }
        public bool ThrowIfCalled { get; init; }

        public Task AssembleAsync(
            IReadOnlyList<string> sourcePaths,
            string outputPath,
            int width,
            int height,
            int fps,
            CancellationToken cancellationToken)
        {
            CallCount++;
            if (ThrowIfCalled)
            {
                throw new InvalidOperationException("FFmpeg 不应被调用");
            }
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
            File.WriteAllBytes(outputPath, "fixture-mp4"u8.ToArray());
            return Task.CompletedTask;
        }
    }

    private sealed class RecordingProcessRunner : IFinalVideoProcessRunner
    {
        public ProcessStartInfo? LastStartInfo { get; private set; }
        public FinalVideoProcessResult Result { get; init; } = new(0, TimedOut: false);

        public Task<FinalVideoProcessResult> RunAsync(
            ProcessStartInfo startInfo,
            TimeSpan timeout,
            CancellationToken cancellationToken)
        {
            LastStartInfo = startInfo;
            if (Result is { ExitCode: 0, TimedOut: false })
            {
                var outputPath = startInfo.ArgumentList[^1];
                Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
                File.WriteAllBytes(outputPath, "fixture-mp4"u8.ToArray());
            }
            return Task.FromResult(Result);
        }
    }
}
