using System.Security.Cryptography;
using System.Text.Json;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>C006B1：本地字节入口、内容寻址安装、重解析点拒绝、Core 登记请求不含路径。</summary>
internal static class TrustedAssetIngressSmokeTests
{
    private const string ScopeKind = TrustedAssetConstants.ScopeAutonomousGoal;
    private const string ScopeId = "goal-0001";

    public static async Task RunAsync()
    {
        var workspace = Path.Combine(Path.GetTempPath(), "picotoo-asset-smoke-" + Guid.NewGuid().ToString("N"));
        var inputRoot = Path.Combine(workspace, "comfy", "input");
        var sources = Path.Combine(workspace, "sources");
        Directory.CreateDirectory(inputRoot);
        Directory.CreateDirectory(sources);
        try
        {
            await VerifySourceRejectionAsync(inputRoot, sources).ConfigureAwait(false);
            await VerifyImportAndReuseAsync(inputRoot, sources).ConfigureAwait(false);
            await VerifyConflictAndRetryAsync(workspace, sources).ConfigureAwait(false);
            await VerifyAncestorReparseAsync(workspace, sources).ConfigureAwait(false);
        }
        finally
        {
            try
            {
                Directory.Delete(workspace, recursive: true);
            }
            catch (IOException)
            {
                // 测试工作区清理为尽力而为。
            }
        }
    }

    private static async Task VerifySourceRejectionAsync(string inputRoot, string sources)
    {
        var service = new TrustedAssetIngressService(inputRoot, new FakeRegistrar());

        await ExpectAsync(service, Path.Combine(sources, "missing.png"), "TRUSTED_ASSET_SOURCE_INVALID", "缺失源必须拒绝")
            .ConfigureAwait(false);
        await ExpectAsync(service, sources, "TRUSTED_ASSET_SOURCE_INVALID", "目录源必须拒绝").ConfigureAwait(false);
        await ExpectAsync(service, "relative.png", "TRUSTED_ASSET_SOURCE_INVALID", "相对路径源必须拒绝")
            .ConfigureAwait(false);

        var fake = Path.Combine(sources, "renamed.png");
        await File.WriteAllTextAsync(fake, "this is not an image").ConfigureAwait(false);
        await ExpectAsync(service, fake, "TRUSTED_ASSET_MEDIA_UNSUPPORTED", "改名的非图片必须拒绝").ConfigureAwait(false);

        var truncated = Path.Combine(sources, "truncated.png");
        var good = CreateImage(8, 8, png: true);
        await File.WriteAllBytesAsync(truncated, good.AsSpan(0, good.Length / 2).ToArray()).ConfigureAwait(false);
        await ExpectAsync(service, truncated, "TRUSTED_ASSET_MEDIA_UNSUPPORTED", "截断图片必须拒绝").ConfigureAwait(false);

        var real = Path.Combine(sources, "real.png");
        await File.WriteAllBytesAsync(real, good).ConfigureAwait(false);
        var link = Path.Combine(sources, "link.png");
        if (TryCreateFileSymlink(link, real))
        {
            await ExpectAsync(service, link, "TRUSTED_ASSET_SOURCE_REPARSE_FORBIDDEN", "重解析点源必须拒绝")
                .ConfigureAwait(false);
        }
        else
        {
            Console.WriteLine("TRUSTED_ASSET_SOURCE_REPARSE=UNVERIFIED(symlink privilege unavailable)");
        }

        SmokeAssert.True(
            !Directory.Exists(Path.Combine(inputRoot, "PicotooPet", "assets", "v1", "aa")),
            "拒绝的导入不得留下最终对象");
    }

    private static async Task VerifyImportAndReuseAsync(string inputRoot, string sources)
    {
        var registrar = new FakeRegistrar();
        var service = new TrustedAssetIngressService(inputRoot, registrar);

        var pngBytes = CreateImage(32, 16, png: true);
        var pngSource = Path.Combine(sources, "photo-original.jpg"); // 扩展名故意错误：类型必须来自字节
        await File.WriteAllBytesAsync(pngSource, pngBytes).ConfigureAwait(false);
        var first = await service.ImportImageAsync(ScopeKind, ScopeId, pngSource, CancellationToken.None)
            .ConfigureAwait(false);

        var sha = Convert.ToHexString(SHA256.HashData(pngBytes)).ToLowerInvariant();
        SmokeAssert.Equal(TrustedAssetConstants.MediaTypePng, first.Record.MediaType, "MIME 必须由字节解码得出");
        SmokeAssert.Equal(32, first.Record.Width, "宽度必须来自解码");
        SmokeAssert.Equal(16, first.Record.Height, "高度必须来自解码");
        SmokeAssert.Equal(sha, first.Record.Sha256, "SHA-256 必须来自暂存字节");
        SmokeAssert.Equal(pngBytes.LongLength, first.Record.SizeBytes, "大小必须来自暂存字节");
        SmokeAssert.True(!first.LocalObjectReused, "首次导入不应是复用");

        var expectedRelative = $"PicotooPet/assets/v1/{sha[..2]}/{sha}.png";
        SmokeAssert.Equal(expectedRelative, first.Record.ManagedRelPath, "最终路径必须只由 SHA+媒体类型推导");
        var finalPath = Path.GetFullPath(Path.Combine(inputRoot, expectedRelative.Replace('/', Path.DirectorySeparatorChar)));
        SmokeAssert.True(
            finalPath.StartsWith(Path.GetFullPath(inputRoot) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase),
            "最终对象必须位于受信根内");
        SmokeAssert.True(File.Exists(finalPath), "最终内容寻址对象缺失");
        SmokeAssert.True(
            (await File.ReadAllBytesAsync(finalPath).ConfigureAwait(false)).AsSpan().SequenceEqual(pngBytes),
            "最终对象字节必须与源一致");
        SmokeAssert.Equal(
            0,
            Directory.GetFiles(Path.Combine(inputRoot, "PicotooPet", "assets", "v1", ".staging")).Length,
            "暂存 .partial 必须清理");

        // 源之后被修改不影响受管对象（快照语义）。
        await File.WriteAllBytesAsync(pngSource, [1, 2, 3]).ConfigureAwait(false);
        SmokeAssert.True(
            (await File.ReadAllBytesAsync(finalPath).ConfigureAwait(false)).AsSpan().SequenceEqual(pngBytes),
            "源变更不得改变受管对象");
        await File.WriteAllBytesAsync(pngSource, pngBytes).ConfigureAwait(false);

        // 请求不含源绝对路径、URL、asset_id、managed_relpath。
        var requestJson = JsonSerializer.Serialize(registrar.Requests[0]);
        SmokeAssert.True(!requestJson.Contains(sources, StringComparison.OrdinalIgnoreCase), "请求不得含源绝对路径");
        SmokeAssert.True(!requestJson.Contains("photo-original", StringComparison.OrdinalIgnoreCase), "请求不得含源文件名");
        foreach (var forbidden in new[] { "asset_id", "managed_relpath", "source_path", "url", "endpoint" })
        {
            SmokeAssert.True(!requestJson.Contains(forbidden, StringComparison.Ordinal), $"请求不得含 {forbidden}");
        }
        SmokeAssert.Equal(TrustedAssetConstants.ManagedRootId, registrar.Requests[0].ManagedRootId, "root id 固定");
        SmokeAssert.True(registrar.Requests[0].DurationMs is null, "图片 duration 必须为 null");

        // 精确复用：同字节再次导入 -> 复用本地对象、同一幂等键、同一资产。
        var second = await service.ImportImageAsync(ScopeKind, ScopeId, pngSource, CancellationToken.None)
            .ConfigureAwait(false);
        SmokeAssert.True(second.LocalObjectReused, "相同对象必须复用");
        SmokeAssert.Equal(first.Record.AssetId, second.Record.AssetId, "重放必须得到同一资产");
        SmokeAssert.Equal(registrar.Requests[0].IdempotencyKey, registrar.Requests[1].IdempotencyKey, "幂等键必须稳定");

        // JPEG 以 .jpg 内容寻址。
        var jpgSource = Path.Combine(sources, "shot.dat");
        var jpgBytes = CreateImage(20, 10, png: false);
        await File.WriteAllBytesAsync(jpgSource, jpgBytes).ConfigureAwait(false);
        var jpeg = await service.ImportImageAsync(ScopeKind, ScopeId, jpgSource, CancellationToken.None)
            .ConfigureAwait(false);
        SmokeAssert.Equal(TrustedAssetConstants.MediaTypeJpeg, jpeg.Record.MediaType, "JPEG 必须由字节识别");
        SmokeAssert.True(jpeg.Record.ManagedRelPath.EndsWith(".jpg", StringComparison.Ordinal), "JPEG 规范扩展名为 jpg");
    }

    private static async Task VerifyConflictAndRetryAsync(string workspace, string sources)
    {
        var inputRoot = Path.Combine(workspace, "comfy2", "input");
        Directory.CreateDirectory(inputRoot);
        var bytes = CreateImage(12, 12, png: true);
        var source = Path.Combine(sources, "conflict.png");
        await File.WriteAllBytesAsync(source, bytes).ConfigureAwait(false);
        var sha = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        var finalPath = Path.Combine(inputRoot, "PicotooPet", "assets", "v1", sha[..2], sha + ".png");

        // 预置同名但内容不同的对象：绝不覆盖。
        Directory.CreateDirectory(Path.GetDirectoryName(finalPath)!);
        var planted = new byte[] { 9, 9, 9, 9 };
        await File.WriteAllBytesAsync(finalPath, planted).ConfigureAwait(false);
        var registrar = new FakeRegistrar();
        var service = new TrustedAssetIngressService(inputRoot, registrar);
        await ExpectAsync(service, source, "TRUSTED_ASSET_LOCAL_CONFLICT", "冲突对象必须拒绝").ConfigureAwait(false);
        SmokeAssert.True(
            (await File.ReadAllBytesAsync(finalPath).ConfigureAwait(false)).AsSpan().SequenceEqual(planted),
            "冲突对象不得被覆盖");
        SmokeAssert.Equal(0, registrar.Requests.Count, "本地冲突时不得登记 Core");
        File.Delete(finalPath);

        // Core 登记失败：只留下无害的内容寻址对象；重试复用对象与同一幂等键。
        registrar.FailuresRemaining = 1;
        await ExpectAsync(service, source, "TRUSTED_ASSET_REGISTRATION_FAILED", "登记失败必须有界报错")
            .ConfigureAwait(false);
        SmokeAssert.True(File.Exists(finalPath), "登记失败后内容寻址对象应保留（无害）");
        SmokeAssert.Equal(
            0,
            Directory.GetFiles(Path.Combine(inputRoot, "PicotooPet", "assets", "v1", ".staging")).Length,
            "登记失败后不得残留 .partial");
        var retried = await service.ImportImageAsync(ScopeKind, ScopeId, source, CancellationToken.None)
            .ConfigureAwait(false);
        SmokeAssert.True(retried.LocalObjectReused, "重试必须复用已安装对象");
        SmokeAssert.Equal(registrar.Requests[0].IdempotencyKey, registrar.Requests[1].IdempotencyKey, "重试必须复用幂等键");

        // Core 返回与请求不一致的事实：拒绝。
        registrar.TamperRelativePath = true;
        await ExpectAsync(service, source, "TRUSTED_ASSET_CORE_MISMATCH", "Core 记录不一致必须拒绝").ConfigureAwait(false);
    }

    private static async Task VerifyAncestorReparseAsync(string workspace, string sources)
    {
        var inputRoot = Path.Combine(workspace, "comfy3", "input");
        var outside = Path.Combine(workspace, "outside");
        Directory.CreateDirectory(inputRoot);
        Directory.CreateDirectory(outside);
        var source = Path.Combine(sources, "ancestor.png");
        await File.WriteAllBytesAsync(source, CreateImage(6, 6, png: true)).ConfigureAwait(false);

        if (!TryCreateDirectorySymlink(Path.Combine(inputRoot, "PicotooPet"), outside))
        {
            Console.WriteLine("TRUSTED_ASSET_ANCESTOR_REPARSE=UNVERIFIED(symlink privilege unavailable)");
            return;
        }
        var service = new TrustedAssetIngressService(inputRoot, new FakeRegistrar());
        await ExpectAsync(service, source, "TRUSTED_ASSET_ROOT_INVALID", "祖先重解析点必须拒绝").ConfigureAwait(false);
        SmokeAssert.Equal(0, Directory.GetFileSystemEntries(outside).Length, "重解析目标目录不得被写入");
    }

    private static async Task ExpectAsync(
        TrustedAssetIngressService service,
        string source,
        string expectedCode,
        string message)
    {
        try
        {
            await service.ImportImageAsync(ScopeKind, ScopeId, source, CancellationToken.None).ConfigureAwait(false);
        }
        catch (TrustedAssetIngressException exception)
        {
            SmokeAssert.Equal(expectedCode, exception.Code, message);
            var sourceDirectory = Path.GetDirectoryName(source);
            SmokeAssert.True(
                string.IsNullOrEmpty(sourceDirectory)
                    || !exception.Message.Contains(sourceDirectory, StringComparison.OrdinalIgnoreCase),
                "错误消息不得包含源路径");
            return;
        }
        throw new InvalidOperationException($"{message}（未抛出）");
    }

    private static byte[] CreateImage(int width, int height, bool png)
    {
        var pixels = new byte[width * height * 4];
        for (var index = 0; index < pixels.Length; index += 4)
        {
            pixels[index] = (byte)(index % 251);
            pixels[index + 1] = (byte)((index / 3) % 251);
            pixels[index + 2] = 200;
            pixels[index + 3] = 255;
        }
        var source = BitmapSource.Create(width, height, 96, 96, PixelFormats.Bgra32, null, pixels, width * 4);
        BitmapEncoder encoder = png ? new PngBitmapEncoder() : new JpegBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(source));
        using var stream = new MemoryStream();
        encoder.Save(stream);
        return stream.ToArray();
    }

    private static bool TryCreateFileSymlink(string link, string target)
    {
        try
        {
            File.CreateSymbolicLink(link, target);
            return true;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    private static bool TryCreateDirectorySymlink(string link, string target)
    {
        try
        {
            Directory.CreateSymbolicLink(link, target);
            return true;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    private sealed class FakeRegistrar : ITrustedAssetRegistrar
    {
        public List<TrustedAssetRegisterRequest> Requests { get; } = [];

        public int FailuresRemaining { get; set; }

        public bool TamperRelativePath { get; set; }

        public Task<TrustedAssetRecord> RegisterAsync(
            TrustedAssetRegisterRequest request,
            CancellationToken cancellationToken)
        {
            Requests.Add(request);
            if (FailuresRemaining > 0)
            {
                FailuresRemaining--;
                throw new HttpRequestException("simulated network ambiguity");
            }
            var relative = TrustedAssetConstants.DeriveRelativePath(request.Sha256, request.MediaType);
            if (TamperRelativePath)
            {
                relative = "PicotooPet/assets/v1/zz/other.png";
            }
            return Task.FromResult(new TrustedAssetRecord(
                "1.0",
                "asset-" + request.Sha256[..12],
                request.ScopeKind,
                request.ScopeId,
                "autonomous-goal:" + request.ScopeId,
                "image",
                "INTERNAL",
                request.ManagedRootId,
                relative,
                request.Sha256,
                request.SizeBytes,
                request.MediaType,
                request.Width,
                request.Height,
                null,
                request.SourceKind,
                new TrustedAssetProvenanceRecord(request.SourceKind, "windows", false),
                "local_only",
                DateTimeOffset.UtcNow));
        }
    }
}
