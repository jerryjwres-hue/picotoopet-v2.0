using System.Diagnostics;
using System.Security.Cryptography;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 C006B2B 受信图片重验、路径边界与固定 FFmpeg 归一化。</summary>
internal static class ProductionExistingAssetSmokeTests
{
    public static async Task RunAsync()
    {
        await RendersVerifiedImageAsync("image/png").ConfigureAwait(false);
        await RendersVerifiedImageAsync("image/jpeg").ConfigureAwait(false);
        await RejectsChangedAndUntrustedFilesAsync().ConfigureAwait(false);
        await TimeoutCleansPartialOutputAsync().ConfigureAwait(false);
    }

    private static async Task RendersVerifiedImageAsync(string mediaType)
    {
        using var input = new TemporaryRoot();
        using var output = new TemporaryRoot();
        var bytes = ImageBytes(mediaType, 12, 8);
        var sha = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        var extension = mediaType == "image/png" ? "png" : "jpg";
        var relpath = $"PicotooPet/assets/v1/{sha[..2]}/{sha}.{extension}";
        var source = Path.Combine(input.Path, relpath.Replace('/', Path.DirectorySeparatorChar));
        Directory.CreateDirectory(Path.GetDirectoryName(source)!);
        File.WriteAllBytes(source, bytes);
        var runner = new RecordingRunner();
        var task = TaskPlan(new ProductionTrustedAssetSnapshotRecord(
            "00000000-0000-4000-8000-0000000006b2", "autonomous_goal", "goal-001",
            "windows.comfy-input.v1", relpath, sha, bytes.Length, mediaType, 12, 8));

        var artifact = await new ProductionLocalMediaRenderer(runner)
            .RenderAsync("job-001", task, output.Path, input.Path, CancellationToken.None)
            .ConfigureAwait(false);

        SmokeAssert.Equal("video/webm", artifact.MimeType, "EXISTING_ASSET 输出不是 WebM");
        SmokeAssert.Equal(480, artifact.Width, "输出宽度未绑定 C005 profile");
        SmokeAssert.Equal(832, artifact.Height, "输出高度未绑定 C005 profile");
        SmokeAssert.Equal(24, artifact.Fps, "输出 fps 未绑定 C005 profile");
        SmokeAssert.Equal(73, artifact.FrameCount, "输出帧数未绑定 C005 profile");
        var startInfo = runner.StartInfo ?? throw new InvalidOperationException("FFmpeg 未执行");
        SmokeAssert.Equal("ffmpeg.exe", startInfo.FileName, "EXISTING_ASSET 可替换 executable");
        SmokeAssert.True(!startInfo.UseShellExecute, "EXISTING_ASSET 使用了 shell");
        var args = startInfo.ArgumentList.ToArray();
        SmokeAssert.True(args.Contains(source, StringComparer.Ordinal), "FFmpeg 未使用已重验受管图片");
        SmokeAssert.True(args.Contains(
            "scale=480:832:force_original_aspect_ratio=decrease,pad=480:832:(ow-iw)/2:(oh-ih)/2:color=0x101820",
            StringComparer.Ordinal), "scale+centered-pad 策略未冻结");
        SmokeAssert.True(args.Contains("libvpx-vp9", StringComparer.Ordinal), "未固定 VP9");
        SmokeAssert.True(args.Contains("yuv420p", StringComparer.Ordinal), "未固定 yuv420p");
        SmokeAssert.True(!args.Contains("-filter_complex", StringComparer.Ordinal), "接受了任意 filter graph");
    }

    private static async Task RejectsChangedAndUntrustedFilesAsync()
    {
        using var input = new TemporaryRoot();
        using var output = new TemporaryRoot();
        var bytes = ImageBytes("image/png", 12, 8);
        var sha = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        var relpath = $"PicotooPet/assets/v1/{sha[..2]}/{sha}.png";
        var source = Path.Combine(input.Path, relpath.Replace('/', Path.DirectorySeparatorChar));
        Directory.CreateDirectory(Path.GetDirectoryName(source)!);
        File.WriteAllBytes(source, bytes);
        var snapshot = new ProductionTrustedAssetSnapshotRecord(
            "00000000-0000-4000-8000-0000000006b2", "autonomous_goal", "goal-001",
            "windows.comfy-input.v1", relpath, sha, bytes.Length, "image/png", 12, 8);
        var renderer = new ProductionLocalMediaRenderer(new RecordingRunner());

        await ExpectThrowsAsync<InvalidDataException>(() => renderer.RenderAsync(
            "job-001", TaskPlan(snapshot with { SizeBytes = bytes.Length + 1 }),
            output.Path, input.Path, CancellationToken.None), "size mismatch 未拒绝").ConfigureAwait(false);
        await ExpectThrowsAsync<InvalidDataException>(() => renderer.RenderAsync(
            "job-001", TaskPlan(snapshot with { Sha256 = new string('0', 64) }),
            output.Path, input.Path, CancellationToken.None), "SHA mismatch 未拒绝").ConfigureAwait(false);
        await ExpectThrowsAsync<InvalidDataException>(() => renderer.RenderAsync(
            "job-001", TaskPlan(snapshot with { MediaType = "image/jpeg" }),
            output.Path, input.Path, CancellationToken.None), "renamed/wrong MIME 未拒绝").ConfigureAwait(false);
        await ExpectThrowsAsync<InvalidDataException>(() => renderer.RenderAsync(
            "job-001", TaskPlan(snapshot with { Width = 13 }),
            output.Path, input.Path, CancellationToken.None), "decoded dimensions mismatch 未拒绝").ConfigureAwait(false);
        await ExpectThrowsAsync<InvalidDataException>(() => renderer.RenderAsync(
            "job-001", TaskPlan(snapshot with { ManagedRelpath = "../escape.png" }),
            output.Path, input.Path, CancellationToken.None), "traversal 未拒绝").ConfigureAwait(false);
        File.Delete(source);
        await ExpectThrowsAsync<FileNotFoundException>(() => renderer.RenderAsync(
            "job-001", TaskPlan(snapshot), output.Path, input.Path, CancellationToken.None),
            "missing file 未拒绝").ConfigureAwait(false);
    }

    private static ProductionTaskPlanRecord TaskPlan(ProductionTrustedAssetSnapshotRecord asset) => new(
        "00000000-0000-4000-8000-0000000006b3", "shot-001", 1, "EXISTING_ASSET",
        "Executable", null, "existing asset", "wan22.safe-negative.v1", 1,
        480, 832, 24, 73, 3000, null, "local_media",
        ProductionLocalMediaRenderer.ExistingImageProfileId, null, asset);

    private static async Task TimeoutCleansPartialOutputAsync()
    {
        using var input = new TemporaryRoot();
        using var output = new TemporaryRoot();
        var bytes = ImageBytes("image/png", 12, 8);
        var sha = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        var relpath = $"PicotooPet/assets/v1/{sha[..2]}/{sha}.png";
        var source = Path.Combine(input.Path, relpath.Replace('/', Path.DirectorySeparatorChar));
        Directory.CreateDirectory(Path.GetDirectoryName(source)!);
        File.WriteAllBytes(source, bytes);
        var task = TaskPlan(new ProductionTrustedAssetSnapshotRecord(
            "00000000-0000-4000-8000-0000000006b2", "autonomous_goal", "goal-001",
            "windows.comfy-input.v1", relpath, sha, bytes.Length, "image/png", 12, 8));
        await ExpectThrowsAsync<TimeoutException>(() =>
            new ProductionLocalMediaRenderer(new TimeoutRunner()).RenderAsync(
                "job-001", task, output.Path, input.Path, CancellationToken.None),
            "timeout 未失败").ConfigureAwait(false);
        SmokeAssert.True(
            !Directory.EnumerateFiles(output.Path, "*.partial.webm", SearchOption.AllDirectories).Any(),
            "timeout 后残留 partial output");
    }

    private static async Task ExpectThrowsAsync<TException>(Func<Task> action, string message)
        where TException : Exception
    {
        try
        {
            await action().ConfigureAwait(false);
        }
        catch (TException)
        {
            return;
        }
        throw new InvalidOperationException(message);
    }

    private static byte[] ImageBytes(string mediaType, int width, int height)
    {
        var pixels = Enumerable.Repeat((byte)127, width * height * 4).ToArray();
        var bitmap = BitmapSource.Create(width, height, 96, 96, PixelFormats.Bgra32, null, pixels, width * 4);
        BitmapEncoder encoder = mediaType == "image/png" ? new PngBitmapEncoder() : new JpegBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var stream = new MemoryStream();
        encoder.Save(stream);
        return stream.ToArray();
    }

    private sealed class RecordingRunner : IProductionLocalMediaProcessRunner
    {
        public ProcessStartInfo? StartInfo { get; private set; }

        public Task<ProductionLocalMediaProcessResult> RunAsync(
            ProcessStartInfo startInfo,
            TimeSpan timeout,
            CancellationToken cancellationToken)
        {
            StartInfo = startInfo;
            var outputPath = startInfo.ArgumentList[^1];
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
            File.WriteAllBytes(outputPath, "deterministic-existing-webm"u8.ToArray());
            return Task.FromResult(new ProductionLocalMediaProcessResult(0, TimedOut: false));
        }
    }

    private sealed class TimeoutRunner : IProductionLocalMediaProcessRunner
    {
        public Task<ProductionLocalMediaProcessResult> RunAsync(
            ProcessStartInfo startInfo,
            TimeSpan timeout,
            CancellationToken cancellationToken)
        {
            var outputPath = startInfo.ArgumentList[^1];
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
            File.WriteAllBytes(outputPath, "partial"u8.ToArray());
            return Task.FromResult(new ProductionLocalMediaProcessResult(null, TimedOut: true));
        }
    }

    private sealed class TemporaryRoot : IDisposable
    {
        public TemporaryRoot()
        {
            Path = System.IO.Path.Combine(
                System.IO.Path.GetTempPath(),
                "picotoopet-existing-asset-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path);
        }

        public string Path { get; }

        public void Dispose() => Directory.Delete(Path, recursive: true);
    }
}
