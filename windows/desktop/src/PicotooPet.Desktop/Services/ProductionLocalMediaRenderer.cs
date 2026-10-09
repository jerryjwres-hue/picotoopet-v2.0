using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

public interface IProductionLocalMediaRenderer
{
    Task<ProductionLocalMediaArtifact> RenderAsync(
        string productionJobId,
        ProductionTaskPlanRecord task,
        string outputRoot,
        string? trustedInputRoot,
        CancellationToken cancellationToken);
}

public interface IProductionLocalMediaProcessRunner
{
    Task<ProductionLocalMediaProcessResult> RunAsync(
        ProcessStartInfo startInfo,
        TimeSpan timeout,
        CancellationToken cancellationToken);
}

public sealed record ProductionLocalMediaProcessResult(int? ExitCode, bool TimedOut);

public sealed record ProductionLocalMediaArtifact(
    string OutputRelpath,
    string OutputPath,
    string OutputSha256,
    long OutputBytes,
    string MimeType,
    int Width,
    int Height,
    int FrameCount,
    int Fps);

/// <summary>使用一个源码内置样式与固定 FFmpeg 参数生成 TEXT_CARD WebM。</summary>
public sealed class ProductionLocalMediaRenderer : IProductionLocalMediaRenderer
{
    public const string TextCardProfileId = "production.local.text-card.v1";
    public const string ExistingImageProfileId = "production.local.existing-image.v1";
    private static readonly TimeSpan FixedTimeout = TimeSpan.FromMinutes(5);
    private readonly IProductionLocalMediaProcessRunner _runner;

    public ProductionLocalMediaRenderer(IProductionLocalMediaProcessRunner runner) =>
        _runner = runner ?? throw new ArgumentNullException(nameof(runner));

    public async Task<ProductionLocalMediaArtifact> RenderAsync(
        string productionJobId,
        ProductionTaskPlanRecord task,
        string outputRoot,
        string? trustedInputRoot,
        CancellationToken cancellationToken)
    {
        ValidateTask(task);
        if (string.Equals(task.ExecutionProfileId, ExistingImageProfileId, StringComparison.Ordinal))
        {
            return await RenderExistingImageAsync(
                productionJobId,
                task,
                outputRoot,
                trustedInputRoot,
                cancellationToken).ConfigureAwait(false);
        }
        cancellationToken.ThrowIfCancellationRequested();
        var root = Path.GetFullPath(outputRoot);
        Directory.CreateDirectory(root);
        ProductionLocalEnvironment.AssertNoLinkEscape(root, root);

        var safeJob = SafeIdentity(productionJobId);
        var safeShot = SafeIdentity(task.ShotId);
        var prefix = $"{task.Order:D3}-{safeShot}-text-card-{task.LocalMedia!.TextDigest[..16]}";
        var relativeDirectory = Path.Combine("PicotooPet", "production", safeJob);
        var relativeOutput = Path.Combine(relativeDirectory, prefix + ".webm");
        var outputPath = ProductionLocalEnvironment.ResolveUnderRoot(
            root,
            relativeOutput,
            requireExistingFile: false);
        var outputDirectory = Path.GetDirectoryName(outputPath)!;
        Directory.CreateDirectory(outputDirectory);
        ProductionLocalEnvironment.AssertNoLinkEscape(root, outputDirectory);
        var framePath = ProductionLocalEnvironment.ResolveUnderRoot(
            root,
            Path.Combine(relativeDirectory, "." + prefix + ".png"),
            requireExistingFile: false);
        var partialPath = ProductionLocalEnvironment.ResolveUnderRoot(
            root,
            Path.Combine(relativeDirectory, "." + prefix + ".partial.webm"),
            requireExistingFile: false);

        try
        {
            DeleteOrdinaryFile(framePath);
            DeleteOrdinaryFile(partialPath);
            RenderTextFrame(framePath, task, cancellationToken);
            var startInfo = BuildStartInfo(framePath, partialPath, task);
            var result = await _runner.RunAsync(startInfo, FixedTimeout, cancellationToken)
                .ConfigureAwait(false);
            if (result.TimedOut)
            {
                throw new TimeoutException("LOCAL_MEDIA_FFMPEG_TIMEOUT");
            }
            if (result.ExitCode != 0)
            {
                throw new InvalidOperationException("LOCAL_MEDIA_FFMPEG_FAILED");
            }
            if (!ProductionLocalEnvironment.IsOrdinaryFile(partialPath))
            {
                throw new InvalidDataException("LOCAL_MEDIA_OUTPUT_MISSING");
            }
            var bytes = new FileInfo(partialPath).Length;
            if (bytes <= 0)
            {
                throw new InvalidDataException("LOCAL_MEDIA_OUTPUT_EMPTY");
            }
            var sha256 = await ProductionLocalEnvironment.Sha256FileAsync(
                partialPath,
                cancellationToken).ConfigureAwait(false);
            DeleteOrdinaryFile(outputPath);
            File.Move(partialPath, outputPath, overwrite: false);
            return new ProductionLocalMediaArtifact(
                relativeOutput.Replace('\\', '/'),
                outputPath,
                sha256,
                bytes,
                "video/webm",
                task.Width,
                task.Height,
                task.FrameCount,
                task.Fps);
        }
        finally
        {
            DeleteOrdinaryFile(framePath);
            DeleteOrdinaryFile(partialPath);
        }
    }

    public Task<ProductionLocalMediaArtifact> RenderAsync(
        string productionJobId,
        ProductionTaskPlanRecord task,
        string outputRoot,
        CancellationToken cancellationToken) =>
        RenderAsync(productionJobId, task, outputRoot, null, cancellationToken);

    private static void ValidateTask(ProductionTaskPlanRecord task)
    {
        if (string.Equals(task.ExecutionProfileId, ExistingImageProfileId, StringComparison.Ordinal))
        {
            var asset = task.TrustedAsset;
            if (!string.Equals(task.RenderIntent, "EXISTING_ASSET", StringComparison.Ordinal)
                || !string.Equals(task.ExecutionDisposition, "Executable", StringComparison.Ordinal)
                || !string.Equals(task.ExecutionBackend, "local_media", StringComparison.Ordinal)
                || task.WorkflowId is not null
                || task.LocalMedia is not null
                || task.TrustedInputAssetRef is not null
                || asset is null
                || !Guid.TryParse(asset.AssetId, out _)
                || !string.Equals(asset.ScopeKind, "autonomous_goal", StringComparison.Ordinal)
                || !string.Equals(asset.ManagedRootId, "windows.comfy-input.v1", StringComparison.Ordinal)
                || (asset.MediaType is not "image/png" and not "image/jpeg")
                || asset.SizeBytes <= 0
                || asset.Width <= 0
                || asset.Height <= 0
                || asset.Sha256.Length != 64
                || task.Width <= 0
                || task.Height <= 0
                || task.Fps <= 0
                || task.FrameCount <= 0)
            {
                throw new InvalidDataException("LOCAL_MEDIA_TRUSTED_ASSET_CONTRACT_INVALID");
            }
            return;
        }
        var payload = task.LocalMedia;
        if (!string.Equals(task.RenderIntent, "TEXT_CARD", StringComparison.Ordinal)
            || !string.Equals(task.ExecutionDisposition, "Executable", StringComparison.Ordinal)
            || !string.Equals(task.ExecutionBackend, "local_media", StringComparison.Ordinal)
            || !string.Equals(task.ExecutionProfileId, TextCardProfileId, StringComparison.Ordinal)
            || task.WorkflowId is not null
            || payload is null
            || !string.Equals(payload.TextProfileId, TextCardProfileId, StringComparison.Ordinal)
            || string.IsNullOrWhiteSpace(payload.TextContent)
            || payload.TextContent.Length > 800
            || task.Width <= 0
            || task.Height <= 0
            || task.Fps <= 0
            || task.FrameCount <= 0)
        {
            throw new InvalidDataException("LOCAL_MEDIA_TASK_CONTRACT_INVALID");
        }
        var digest = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(payload.TextContent)))
            .ToLowerInvariant();
        if (!string.Equals(digest, payload.TextDigest, StringComparison.Ordinal))
        {
            throw new InvalidDataException("LOCAL_MEDIA_TEXT_DIGEST_MISMATCH");
        }
    }

    private async Task<ProductionLocalMediaArtifact> RenderExistingImageAsync(
        string productionJobId,
        ProductionTaskPlanRecord task,
        string outputRoot,
        string? trustedInputRoot,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(trustedInputRoot))
        {
            throw new InvalidDataException("LOCAL_MEDIA_TRUSTED_INPUT_ROOT_MISSING");
        }
        cancellationToken.ThrowIfCancellationRequested();
        var asset = task.TrustedAsset!;
        var inputRoot = Path.GetFullPath(trustedInputRoot);
        ProductionLocalEnvironment.AssertNoLinkEscape(inputRoot, inputRoot);
        var sourcePath = ProductionLocalEnvironment.ResolveUnderRoot(
            inputRoot,
            asset.ManagedRelpath,
            requireExistingFile: true);
        ProductionLocalEnvironment.AssertNoLinkEscape(inputRoot, sourcePath);
        if (!ProductionLocalEnvironment.IsOrdinaryFile(sourcePath))
        {
            throw new InvalidDataException("LOCAL_MEDIA_TRUSTED_ASSET_FILE_INVALID");
        }
        if (new FileInfo(sourcePath).Length != asset.SizeBytes)
        {
            throw new InvalidDataException("LOCAL_MEDIA_TRUSTED_ASSET_SIZE_MISMATCH");
        }
        var digest = await ProductionLocalEnvironment.Sha256FileAsync(sourcePath, cancellationToken)
            .ConfigureAwait(false);
        if (!string.Equals(digest, asset.Sha256, StringComparison.Ordinal))
        {
            throw new InvalidDataException("LOCAL_MEDIA_TRUSTED_ASSET_SHA256_MISMATCH");
        }
        VerifyImageFacts(sourcePath, asset);

        var root = Path.GetFullPath(outputRoot);
        Directory.CreateDirectory(root);
        ProductionLocalEnvironment.AssertNoLinkEscape(root, root);
        var safeJob = SafeIdentity(productionJobId);
        var safeShot = SafeIdentity(task.ShotId);
        var prefix = $"{task.Order:D3}-{safeShot}-existing-{asset.Sha256[..16]}";
        var relativeDirectory = Path.Combine("PicotooPet", "production", safeJob);
        var relativeOutput = Path.Combine(relativeDirectory, prefix + ".webm");
        var outputPath = ProductionLocalEnvironment.ResolveUnderRoot(root, relativeOutput, false);
        var outputDirectory = Path.GetDirectoryName(outputPath)!;
        Directory.CreateDirectory(outputDirectory);
        ProductionLocalEnvironment.AssertNoLinkEscape(root, outputDirectory);
        var partialPath = ProductionLocalEnvironment.ResolveUnderRoot(
            root,
            Path.Combine(relativeDirectory, "." + prefix + ".partial.webm"),
            false);
        try
        {
            DeleteOrdinaryFile(partialPath);
            var result = await _runner.RunAsync(
                BuildExistingImageStartInfo(sourcePath, partialPath, task),
                FixedTimeout,
                cancellationToken).ConfigureAwait(false);
            if (result.TimedOut)
            {
                throw new TimeoutException("LOCAL_MEDIA_FFMPEG_TIMEOUT");
            }
            if (result.ExitCode != 0)
            {
                throw new InvalidOperationException("LOCAL_MEDIA_FFMPEG_FAILED");
            }
            if (!ProductionLocalEnvironment.IsOrdinaryFile(partialPath))
            {
                throw new InvalidDataException("LOCAL_MEDIA_OUTPUT_MISSING");
            }
            var bytes = new FileInfo(partialPath).Length;
            if (bytes <= 0)
            {
                throw new InvalidDataException("LOCAL_MEDIA_OUTPUT_EMPTY");
            }
            var sha256 = await ProductionLocalEnvironment.Sha256FileAsync(partialPath, cancellationToken)
                .ConfigureAwait(false);
            DeleteOrdinaryFile(outputPath);
            File.Move(partialPath, outputPath, overwrite: false);
            return new ProductionLocalMediaArtifact(
                relativeOutput.Replace('\\', '/'), outputPath, sha256, bytes, "video/webm",
                task.Width, task.Height, task.FrameCount, task.Fps);
        }
        finally
        {
            DeleteOrdinaryFile(partialPath);
        }
    }

    private static void VerifyImageFacts(
        string sourcePath,
        ProductionTrustedAssetSnapshotRecord asset)
    {
        using var stream = new FileStream(sourcePath, FileMode.Open, FileAccess.Read, FileShare.Read);
        Span<byte> header = stackalloc byte[8];
        if (stream.Read(header) != header.Length)
        {
            throw new InvalidDataException("LOCAL_MEDIA_TRUSTED_ASSET_DECODE_FAILED");
        }
        var isPng = header.SequenceEqual(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 });
        var isJpeg = header[0] == 0xff && header[1] == 0xd8 && header[2] == 0xff;
        var decodedMediaType = isPng ? "image/png" : isJpeg ? "image/jpeg" : null;
        if (!string.Equals(decodedMediaType, asset.MediaType, StringComparison.Ordinal))
        {
            throw new InvalidDataException("LOCAL_MEDIA_TRUSTED_ASSET_MIME_MISMATCH");
        }
        stream.Position = 0;
        BitmapDecoder decoder;
        try
        {
            decoder = BitmapDecoder.Create(
                stream,
                BitmapCreateOptions.PreservePixelFormat,
                BitmapCacheOption.OnLoad);
        }
        catch (Exception exception) when (exception is NotSupportedException or FileFormatException)
        {
            throw new InvalidDataException("LOCAL_MEDIA_TRUSTED_ASSET_DECODE_FAILED", exception);
        }
        var frame = decoder.Frames.FirstOrDefault()
            ?? throw new InvalidDataException("LOCAL_MEDIA_TRUSTED_ASSET_DECODE_FAILED");
        if (frame.PixelWidth != asset.Width || frame.PixelHeight != asset.Height)
        {
            throw new InvalidDataException("LOCAL_MEDIA_TRUSTED_ASSET_DIMENSION_MISMATCH");
        }
    }

    private static ProcessStartInfo BuildExistingImageStartInfo(
        string sourcePath,
        string partialPath,
        ProductionTaskPlanRecord task)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = "ffmpeg.exe",
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        var filter = $"scale={task.Width}:{task.Height}:force_original_aspect_ratio=decrease," +
            $"pad={task.Width}:{task.Height}:(ow-iw)/2:(oh-ih)/2:color=0x101820";
        foreach (var argument in new[]
        {
            "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-loop", "1", "-framerate", Invariant(task.Fps), "-i", sourcePath,
            "-vf", filter, "-frames:v", Invariant(task.FrameCount), "-an",
            "-c:v", "libvpx-vp9", "-deadline", "good", "-cpu-used", "2",
            "-threads", "1", "-row-mt", "0", "-pix_fmt", "yuv420p",
            "-r", Invariant(task.Fps), "-map_metadata", "-1", "-fflags", "+bitexact",
            "-flags:v", "+bitexact", "-f", "webm", partialPath,
        })
        {
            startInfo.ArgumentList.Add(argument);
        }
        return startInfo;
    }

    private static ProcessStartInfo BuildStartInfo(
        string framePath,
        string partialPath,
        ProductionTaskPlanRecord task)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = "ffmpeg.exe",
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var argument in new[]
        {
            "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-loop", "1", "-framerate", Invariant(task.Fps), "-i", framePath,
            "-frames:v", Invariant(task.FrameCount), "-an",
            "-c:v", "libvpx-vp9", "-deadline", "good", "-cpu-used", "2",
            "-threads", "1", "-row-mt", "0", "-pix_fmt", "yuv420p",
            "-r", Invariant(task.Fps), "-s", $"{task.Width}x{task.Height}",
            "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
            "-f", "webm", partialPath,
        })
        {
            startInfo.ArgumentList.Add(argument);
        }
        return startInfo;
    }

    private static void RenderTextFrame(
        string framePath,
        ProductionTaskPlanRecord task,
        CancellationToken cancellationToken)
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                cancellationToken.ThrowIfCancellationRequested();
                var visual = new DrawingVisual();
                using (var context = visual.RenderOpen())
                {
                    context.DrawRectangle(
                        new SolidColorBrush(System.Windows.Media.Color.FromRgb(16, 24, 32)),
                        null,
                        new Rect(0, 0, task.Width, task.Height));
                    var fontSize = Math.Max(24.0, Math.Min(task.Width, task.Height) / 10.0);
                    var formatted = new FormattedText(
                        task.LocalMedia!.TextContent,
                        CultureInfo.GetCultureInfo("en-US"),
                        System.Windows.FlowDirection.LeftToRight,
                        new Typeface(
                            new System.Windows.Media.FontFamily("Segoe UI"),
                            FontStyles.Normal,
                            FontWeights.SemiBold,
                            FontStretches.Normal),
                        fontSize,
                        System.Windows.Media.Brushes.White,
                        1.0)
                    {
                        MaxTextWidth = task.Width * 0.8,
                        MaxTextHeight = task.Height * 0.8,
                        TextAlignment = TextAlignment.Center,
                    };
                    var x = (task.Width - formatted.MaxTextWidth) / 2.0;
                    var y = Math.Max(task.Height * 0.1, (task.Height - formatted.Height) / 2.0);
                    context.DrawText(formatted, new System.Windows.Point(x, y));
                }
                var bitmap = new RenderTargetBitmap(
                    task.Width,
                    task.Height,
                    96,
                    96,
                    PixelFormats.Pbgra32);
                bitmap.Render(visual);
                var encoder = new PngBitmapEncoder();
                encoder.Frames.Add(BitmapFrame.Create(bitmap));
                using var stream = new FileStream(framePath, FileMode.CreateNew, FileAccess.Write, FileShare.None);
                encoder.Save(stream);
            }
            catch (Exception exception)
            {
                failure = exception;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        if (failure is not null)
        {
            throw new InvalidOperationException("LOCAL_MEDIA_TEXT_RENDER_FAILED", failure);
        }
    }

    private static string SafeIdentity(string value)
    {
        var normalized = new string(value
            .Select(character => char.IsLetterOrDigit(character) || character is '-' or '_' ? character : '-')
            .Take(120)
            .ToArray());
        return string.IsNullOrWhiteSpace(normalized) ? "unknown" : normalized;
    }

    private static string Invariant(int value) =>
        value.ToString(CultureInfo.InvariantCulture);

    private static void DeleteOrdinaryFile(string path)
    {
        if (File.Exists(path))
        {
            if (!ProductionLocalEnvironment.IsOrdinaryFile(path))
            {
                throw new InvalidDataException("LOCAL_MEDIA_REPARSE_POINT_FORBIDDEN");
            }
            File.Delete(path);
        }
    }
}

/// <summary>仅允许固定 ffmpeg.exe、ArgumentList 与无 shell 执行。</summary>
public sealed class ProductionLocalMediaProcessRunner : IProductionLocalMediaProcessRunner
{
    public async Task<ProductionLocalMediaProcessResult> RunAsync(
        ProcessStartInfo startInfo,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        if (!string.Equals(startInfo.FileName, "ffmpeg.exe", StringComparison.OrdinalIgnoreCase)
            || startInfo.UseShellExecute)
        {
            throw new InvalidOperationException("LOCAL_MEDIA_EXECUTABLE_POLICY_DENIED");
        }
        using var process = new Process { StartInfo = startInfo };
        try
        {
            if (!process.Start())
            {
                throw new InvalidOperationException("LOCAL_MEDIA_FFMPEG_START_FAILED");
            }
        }
        catch (Win32Exception exception)
        {
            throw new InvalidOperationException("LOCAL_MEDIA_FFMPEG_UNAVAILABLE", exception);
        }
        var stdout = process.StandardOutput.ReadToEndAsync(cancellationToken);
        var stderr = process.StandardError.ReadToEndAsync(cancellationToken);
        using var timeoutCancellation = new CancellationTokenSource(timeout);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(
            cancellationToken,
            timeoutCancellation.Token);
        try
        {
            await process.WaitForExitAsync(linked.Token).ConfigureAwait(false);
            _ = await stdout.ConfigureAwait(false);
            _ = await stderr.ConfigureAwait(false);
            return new ProductionLocalMediaProcessResult(process.ExitCode, TimedOut: false);
        }
        catch (OperationCanceledException) when (
            timeoutCancellation.IsCancellationRequested && !cancellationToken.IsCancellationRequested)
        {
            TryKill(process);
            return new ProductionLocalMediaProcessResult(null, TimedOut: true);
        }
        catch (OperationCanceledException)
        {
            TryKill(process);
            throw;
        }
    }

    private static void TryKill(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch (InvalidOperationException)
        {
        }
    }
}
