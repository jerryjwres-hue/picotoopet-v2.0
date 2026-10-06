using System.ComponentModel;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

public interface IProductionPackageGateway
{
    Task<ProductionPackageRecord?> GetProductionPackageAsync(
        string productionJobId,
        CancellationToken cancellationToken);
}

public interface IFinalVideoAssembler
{
    Task<FinalVideoArtifact> AssembleAsync(
        string productionJobId,
        CancellationToken cancellationToken = default);
}

public interface IFinalVideoFfmpeg
{
    Task AssembleAsync(
        IReadOnlyList<string> sourcePaths,
        string outputPath,
        int width,
        int height,
        int fps,
        CancellationToken cancellationToken);
}

public interface IFinalVideoProcessRunner
{
    Task<FinalVideoProcessResult> RunAsync(
        ProcessStartInfo startInfo,
        TimeSpan timeout,
        CancellationToken cancellationToken);
}

public sealed record FinalVideoProcessResult(int? ExitCode, bool TimedOut);

public sealed record FinalVideoSourceOutput(
    string OutputRelpath,
    string OutputSha256,
    long OutputBytes,
    string MimeType,
    int Width,
    int Height,
    int FrameCount,
    int Fps);

public sealed record FinalVideoArtifact(
    string ProductionJobId,
    string ProductionPackageId,
    string ProductionPackageDigest,
    string FilePath,
    string ManifestPath,
    string Sha256,
    long Bytes,
    bool Reused);

/// <summary>仅使用固定 ffmpeg.exe 与内部参数生成普通 Windows 可播放 MP4。</summary>
public sealed class FixedFfmpegAssembler : IFinalVideoFfmpeg
{
    private static readonly TimeSpan FixedTimeout = TimeSpan.FromMinutes(30);
    private readonly IFinalVideoProcessRunner _runner;

    public FixedFfmpegAssembler(IFinalVideoProcessRunner runner) =>
        _runner = runner ?? throw new ArgumentNullException(nameof(runner));

    public async Task AssembleAsync(
        IReadOnlyList<string> sourcePaths,
        string outputPath,
        int width,
        int height,
        int fps,
        CancellationToken cancellationToken)
    {
        if (sourcePaths.Count == 0 || width <= 0 || height <= 0 || fps <= 0)
        {
            throw new InvalidDataException("FINAL_VIDEO_MEDIA_PROPERTIES_INVALID");
        }
        var startInfo = new ProcessStartInfo
        {
            FileName = "ffmpeg.exe",
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var argument in new[] { "-hide_banner", "-loglevel", "error", "-nostdin", "-y" })
        {
            startInfo.ArgumentList.Add(argument);
        }
        foreach (var sourcePath in sourcePaths)
        {
            startInfo.ArgumentList.Add("-i");
            startInfo.ArgumentList.Add(sourcePath);
        }
        var filter = string.Concat(
            sourcePaths.Select((_, index) => $"[{index}:v:0]setpts=PTS-STARTPTS[v{index}];"))
            + string.Concat(sourcePaths.Select((_, index) => $"[v{index}]"))
            + $"concat=n={sourcePaths.Count}:v=1:a=0[outv]";
        foreach (var argument in new[]
        {
            "-filter_complex", filter,
            "-map", "[outv]",
            "-an",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-r", fps.ToString(System.Globalization.CultureInfo.InvariantCulture),
            "-s", $"{width}x{height}",
            "-f", "mp4",
            outputPath,
        })
        {
            startInfo.ArgumentList.Add(argument);
        }

        var result = await _runner.RunAsync(startInfo, FixedTimeout, cancellationToken)
            .ConfigureAwait(false);
        if (result.TimedOut)
        {
            throw new TimeoutException("FINAL_VIDEO_FFMPEG_TIMEOUT");
        }
        if (result.ExitCode != 0)
        {
            throw new InvalidOperationException("FINAL_VIDEO_FFMPEG_FAILED");
        }
    }
}

/// <summary>执行固定进程边界；输出只被排空，不进入 UI 或持久化。</summary>
public sealed class FinalVideoProcessRunner : IFinalVideoProcessRunner
{
    public async Task<FinalVideoProcessResult> RunAsync(
        ProcessStartInfo startInfo,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        if (!string.Equals(startInfo.FileName, "ffmpeg.exe", StringComparison.OrdinalIgnoreCase)
            || startInfo.UseShellExecute)
        {
            throw new InvalidOperationException("FINAL_VIDEO_EXECUTABLE_POLICY_DENIED");
        }

        using var process = new Process { StartInfo = startInfo };
        try
        {
            if (!process.Start())
            {
                throw new InvalidOperationException("FINAL_VIDEO_FFMPEG_START_FAILED");
            }
        }
        catch (Win32Exception)
        {
            throw new InvalidOperationException("FINAL_VIDEO_FFMPEG_UNAVAILABLE");
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
            return new FinalVideoProcessResult(process.ExitCode, TimedOut: false);
        }
        catch (OperationCanceledException) when (
            timeoutCancellation.IsCancellationRequested && !cancellationToken.IsCancellationRequested)
        {
            TryKill(process);
            return new FinalVideoProcessResult(null, TimedOut: true);
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
            // Process 已退出。
        }
    }
}

/// <summary>从 Core Production Package 派生并验证一个本地不可变最终视频。</summary>
public sealed class FinalVideoAssemblyService : IFinalVideoAssembler
{
    private const string ManifestSchemaVersion = "1.0";
    private static readonly JsonSerializerOptions ManifestJsonOptions = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    private readonly IProductionPackageGateway _gateway;
    private readonly IFinalVideoFfmpeg _ffmpeg;
    private readonly Func<string> _outputRootResolver;
    private readonly Func<string> _finalRootResolver;
    private readonly TimeProvider _timeProvider;

    public FinalVideoAssemblyService(
        IProductionPackageGateway gateway,
        IFinalVideoFfmpeg ffmpeg,
        string outputRoot,
        string finalRoot,
        TimeProvider timeProvider)
        : this(gateway, ffmpeg, () => outputRoot, () => finalRoot, timeProvider)
    {
    }

    private FinalVideoAssemblyService(
        IProductionPackageGateway gateway,
        IFinalVideoFfmpeg ffmpeg,
        Func<string> outputRootResolver,
        Func<string> finalRootResolver,
        TimeProvider timeProvider)
    {
        _gateway = gateway ?? throw new ArgumentNullException(nameof(gateway));
        _ffmpeg = ffmpeg ?? throw new ArgumentNullException(nameof(ffmpeg));
        _outputRootResolver = outputRootResolver;
        _finalRootResolver = finalRootResolver;
        _timeProvider = timeProvider;
    }

    public static FinalVideoAssemblyService Create(ControlCenterSession session) =>
        new(
            session,
            new FixedFfmpegAssembler(new FinalVideoProcessRunner()),
            ProductionLocalEnvironment.ResolveComfyOutputRoot,
            ResolveManagedFinalRoot,
            TimeProvider.System);

    public async Task<FinalVideoArtifact> AssembleAsync(
        string productionJobId,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(productionJobId))
        {
            throw new ArgumentException("FINAL_VIDEO_JOB_ID_REQUIRED", nameof(productionJobId));
        }
        var package = await _gateway.GetProductionPackageAsync(productionJobId, cancellationToken)
            .ConfigureAwait(false)
            ?? throw new InvalidOperationException("FINAL_VIDEO_PACKAGE_NOT_FOUND");
        if (!string.Equals(package.ProductionJobId, productionJobId, StringComparison.Ordinal)
            || !string.Equals(package.QualityOutcome, "PASS", StringComparison.Ordinal))
        {
            throw new InvalidDataException("FINAL_VIDEO_PACKAGE_IDENTITY_INVALID");
        }

        var outputs = ParseOutputs(package);
        var outputRoot = Path.GetFullPath(_outputRootResolver());
        var verifiedSources = await VerifySourcesAsync(outputRoot, outputs, cancellationToken)
            .ConfigureAwait(false);
        var finalRoot = Path.GetFullPath(_finalRootResolver());
        Directory.CreateDirectory(finalRoot);
        ProductionLocalEnvironment.AssertNoLinkEscape(finalRoot, finalRoot);

        var identity = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(productionJobId)))
            .ToLowerInvariant()[..32];
        var finalFileName = $"final-{identity}.mp4";
        var manifestFileName = $"final-{identity}.final-video.json";
        var finalPath = ProductionLocalEnvironment.ResolveUnderRoot(finalRoot, finalFileName, requireExistingFile: false);
        var manifestPath = ProductionLocalEnvironment.ResolveUnderRoot(finalRoot, manifestFileName, requireExistingFile: false);
        var sourceHashes = outputs.Select(item => item.OutputSha256).ToArray();

        if (File.Exists(finalPath) || File.Exists(manifestPath))
        {
            return await ReuseExistingAsync(
                package,
                finalRoot,
                finalPath,
                manifestPath,
                finalFileName,
                sourceHashes,
                cancellationToken).ConfigureAwait(false);
        }

        var partialPath = ProductionLocalEnvironment.ResolveUnderRoot(
            finalRoot,
            $".{finalFileName}.{Guid.NewGuid():N}.partial.mp4",
            requireExistingFile: false);
        try
        {
            var media = outputs[0];
            await _ffmpeg.AssembleAsync(
                verifiedSources,
                partialPath,
                media.Width,
                media.Height,
                media.Fps,
                cancellationToken).ConfigureAwait(false);
            if (!ProductionLocalEnvironment.IsOrdinaryFile(partialPath))
            {
                throw new InvalidDataException("FINAL_VIDEO_OUTPUT_MISSING");
            }
            var bytes = new FileInfo(partialPath).Length;
            if (bytes <= 0)
            {
                throw new InvalidDataException("FINAL_VIDEO_OUTPUT_EMPTY");
            }
            var finalSha256 = await ProductionLocalEnvironment.Sha256FileAsync(partialPath, cancellationToken)
                .ConfigureAwait(false);
            File.Move(partialPath, finalPath, overwrite: false);

            var manifest = new LocalFinalVideoManifest(
                ManifestSchemaVersion,
                package.ProductionJobId,
                package.ProductionPackageId,
                package.PackageDigest,
                sourceHashes,
                finalFileName,
                finalSha256,
                bytes,
                _timeProvider.GetUtcNow());
            var manifestTemporary = manifestPath + ".partial";
            await File.WriteAllTextAsync(
                manifestTemporary,
                JsonSerializer.Serialize(manifest, ManifestJsonOptions),
                Encoding.UTF8,
                cancellationToken).ConfigureAwait(false);
            File.Move(manifestTemporary, manifestPath, overwrite: false);
            return new FinalVideoArtifact(
                productionJobId,
                package.ProductionPackageId,
                package.PackageDigest,
                finalPath,
                manifestPath,
                finalSha256,
                bytes,
                Reused: false);
        }
        finally
        {
            if (File.Exists(partialPath))
            {
                File.Delete(partialPath);
            }
        }
    }

    private static FinalVideoSourceOutput[] ParseOutputs(ProductionPackageRecord package)
    {
        var manifest = package.Manifest;
        if (manifest.ValueKind != JsonValueKind.Object
            || !TryGetString(manifest, "schema_version", out var schemaVersion)
            || !string.Equals(schemaVersion, "1.0", StringComparison.Ordinal)
            || !TryGetString(manifest, "production_package_id", out var manifestPackageId)
            || !string.Equals(manifestPackageId, package.ProductionPackageId, StringComparison.Ordinal)
            || !TryGetString(manifest, "production_job_id", out var manifestJobId)
            || !string.Equals(manifestJobId, package.ProductionJobId, StringComparison.Ordinal)
            || !manifest.TryGetProperty("outputs", out var outputArray)
            || outputArray.ValueKind != JsonValueKind.Array
            || outputArray.GetArrayLength() == 0)
        {
            throw new InvalidDataException("FINAL_VIDEO_PACKAGE_MANIFEST_INVALID");
        }

        var outputs = new List<FinalVideoSourceOutput>();
        foreach (var item in outputArray.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object
                || !TryGetString(item, "output_relpath", out var relative)
                || !TryGetString(item, "output_sha256", out var sha256)
                || !TryGetString(item, "mime_type", out var mime)
                || !item.TryGetProperty("output_bytes", out var bytesNode)
                || !bytesNode.TryGetInt64(out var bytes)
                || !item.TryGetProperty("width", out var widthNode)
                || !widthNode.TryGetInt32(out var width)
                || !item.TryGetProperty("height", out var heightNode)
                || !heightNode.TryGetInt32(out var height)
                || !item.TryGetProperty("frame_count", out var frameNode)
                || !frameNode.TryGetInt32(out var frameCount)
                || !item.TryGetProperty("fps", out var fpsNode)
                || !fpsNode.TryGetInt32(out var fps))
            {
                throw new InvalidDataException("FINAL_VIDEO_SOURCE_FACTS_INVALID");
            }
            outputs.Add(new FinalVideoSourceOutput(
                relative,
                sha256,
                bytes,
                mime,
                width,
                height,
                frameCount,
                fps));
        }

        var first = outputs[0];
        if (first.Width <= 0 || first.Height <= 0 || first.FrameCount <= 0 || first.Fps <= 0
            || outputs.Any(item => item.Width != first.Width
                || item.Height != first.Height
                || item.Fps != first.Fps
                || item.FrameCount <= 0))
        {
            throw new InvalidDataException("FINAL_VIDEO_MEDIA_PROPERTIES_INCOMPATIBLE");
        }
        return outputs.ToArray();
    }

    private static async Task<string[]> VerifySourcesAsync(
        string outputRoot,
        FinalVideoSourceOutput[] outputs,
        CancellationToken cancellationToken)
    {
        var paths = new List<string>(outputs.Length);
        foreach (var output in outputs)
        {
            if (!string.Equals(output.MimeType, "video/webm", StringComparison.OrdinalIgnoreCase)
                || output.OutputBytes <= 0
                || output.OutputSha256.Length != 64
                || output.OutputSha256.Any(character => !Uri.IsHexDigit(character)))
            {
                throw new InvalidDataException("FINAL_VIDEO_SOURCE_FACTS_INVALID");
            }
            var path = ProductionLocalEnvironment.ResolveUnderRoot(
                outputRoot,
                output.OutputRelpath,
                requireExistingFile: true);
            ProductionLocalEnvironment.AssertNoLinkEscape(outputRoot, path);
            if (!ProductionLocalEnvironment.IsOrdinaryFile(path)
                || new FileInfo(path).Length != output.OutputBytes)
            {
                throw new InvalidDataException("FINAL_VIDEO_SOURCE_FILE_INVALID");
            }
            var actual = await ProductionLocalEnvironment.Sha256FileAsync(path, cancellationToken)
                .ConfigureAwait(false);
            if (!string.Equals(actual, output.OutputSha256, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("FINAL_VIDEO_SOURCE_HASH_MISMATCH");
            }
            paths.Add(path);
        }
        return paths.ToArray();
    }

    private static async Task<FinalVideoArtifact> ReuseExistingAsync(
        ProductionPackageRecord package,
        string finalRoot,
        string finalPath,
        string manifestPath,
        string finalFileName,
        string[] sourceHashes,
        CancellationToken cancellationToken)
    {
        try
        {
            if (!ProductionLocalEnvironment.IsOrdinaryFile(finalPath)
                || !ProductionLocalEnvironment.IsOrdinaryFile(manifestPath))
            {
                throw new InvalidDataException("FINAL_VIDEO_ARTIFACT_CONFLICT");
            }
            ProductionLocalEnvironment.AssertNoLinkEscape(finalRoot, finalPath);
            ProductionLocalEnvironment.AssertNoLinkEscape(finalRoot, manifestPath);
            var manifest = JsonSerializer.Deserialize<LocalFinalVideoManifest>(
                await File.ReadAllTextAsync(manifestPath, cancellationToken).ConfigureAwait(false),
                ManifestJsonOptions) ?? throw new InvalidDataException("FINAL_VIDEO_ARTIFACT_CONFLICT");
            var bytes = new FileInfo(finalPath).Length;
            var digest = await ProductionLocalEnvironment.Sha256FileAsync(finalPath, cancellationToken)
                .ConfigureAwait(false);
            if (!string.Equals(manifest.SchemaVersion, ManifestSchemaVersion, StringComparison.Ordinal)
                || !string.Equals(manifest.ProductionJobId, package.ProductionJobId, StringComparison.Ordinal)
                || !string.Equals(manifest.ProductionPackageId, package.ProductionPackageId, StringComparison.Ordinal)
                || !string.Equals(manifest.ProductionPackageDigest, package.PackageDigest, StringComparison.Ordinal)
                || !manifest.SourceOutputSha256.SequenceEqual(sourceHashes, StringComparer.OrdinalIgnoreCase)
                || !string.Equals(manifest.FinalFileName, finalFileName, StringComparison.Ordinal)
                || !string.Equals(manifest.FinalSha256, digest, StringComparison.OrdinalIgnoreCase)
                || manifest.FinalBytes != bytes)
            {
                throw new InvalidDataException("FINAL_VIDEO_ARTIFACT_CONFLICT");
            }
            return new FinalVideoArtifact(
                package.ProductionJobId,
                package.ProductionPackageId,
                package.PackageDigest,
                finalPath,
                manifestPath,
                digest,
                bytes,
                Reused: true);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (InvalidDataException)
        {
            throw;
        }
        catch (Exception)
        {
            throw new InvalidDataException("FINAL_VIDEO_ARTIFACT_CONFLICT");
        }
    }

    private static bool TryGetString(JsonElement element, string name, out string value)
    {
        value = string.Empty;
        if (!element.TryGetProperty(name, out var property) || property.ValueKind != JsonValueKind.String)
        {
            return false;
        }
        value = property.GetString() ?? string.Empty;
        return !string.IsNullOrWhiteSpace(value);
    }

    private static string ResolveManagedFinalRoot()
    {
        var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(localAppData))
        {
            throw new DirectoryNotFoundException("LOCAL_APP_DATA_NOT_FOUND");
        }
        return Path.Combine(localAppData, "PicotooPet", "FinalVideos");
    }

    private sealed record LocalFinalVideoManifest(
        [property: JsonPropertyName("schema_version")] string SchemaVersion,
        [property: JsonPropertyName("production_job_id")] string ProductionJobId,
        [property: JsonPropertyName("production_package_id")] string ProductionPackageId,
        [property: JsonPropertyName("production_package_digest")] string ProductionPackageDigest,
        [property: JsonPropertyName("source_output_sha256")] string[] SourceOutputSha256,
        [property: JsonPropertyName("final_file_name")] string FinalFileName,
        [property: JsonPropertyName("final_sha256")] string FinalSha256,
        [property: JsonPropertyName("final_bytes")] long FinalBytes,
        [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);
}
