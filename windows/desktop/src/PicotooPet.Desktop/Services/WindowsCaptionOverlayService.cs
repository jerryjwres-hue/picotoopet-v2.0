using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>C008B 派生视觉产物；passthrough 时 FilePath/Sha256 就是已验证的 C004 源。</summary>
public sealed record TextOverlayArtifact(
    string ProductionJobId,
    string SourceFinalSha256,
    string CaptionOverlayPlanDigest,
    string OutputProfileId,
    string FilePath,
    string? ManifestPath,
    string Sha256,
    long Bytes,
    bool Passthrough,
    bool Reused);

/// <summary>
/// 把 C008A2 叠加计划应用到已验证的 C004 FinalVideoArtifact。调用方不能提供源/输出/字体/滤镜路径：
/// 源必须位于 C004 托管根并重新校验字节与 SHA；输出只写入固定托管根；清单不含文案或绝对路径。
/// </summary>
public sealed class WindowsCaptionOverlayService
{
    public const string ManifestSchemaVersion = "1.0";
    private static readonly JsonSerializerOptions ManifestJson = new()
    {
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };

    private readonly WindowsCaptionOverlayRenderer _renderer;
    private readonly WindowsTextOverlayFontPolicy _fonts;
    private readonly Func<string> _finalRootResolver;
    private readonly Func<string> _overlayRootResolver;
    private readonly TimeProvider _timeProvider;

    public WindowsCaptionOverlayService(
        WindowsCaptionOverlayRenderer renderer,
        WindowsTextOverlayFontPolicy fonts,
        string finalVideoRoot,
        string overlayRoot,
        TimeProvider timeProvider)
    {
        _renderer = renderer ?? throw new ArgumentNullException(nameof(renderer));
        _fonts = fonts ?? throw new ArgumentNullException(nameof(fonts));
        _finalRootResolver = () => finalVideoRoot;
        _overlayRootResolver = () => overlayRoot;
        _timeProvider = timeProvider ?? throw new ArgumentNullException(nameof(timeProvider));
    }

    /// <summary>生产组合：固定 C004 托管根与 %LOCALAPPDATA%\PicotooPet\PostProduction\TextOverlay\v1。</summary>
    public static WindowsCaptionOverlayService Create()
    {
        var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(localAppData))
        {
            throw new DirectoryNotFoundException("LOCAL_APP_DATA_NOT_FOUND");
        }
        return new WindowsCaptionOverlayService(
            new WindowsCaptionOverlayRenderer(new TextOverlayProcessRunner()),
            new WindowsTextOverlayFontPolicy(),
            Path.Combine(localAppData, "PicotooPet", "FinalVideos"),
            Path.Combine(localAppData, "PicotooPet", "PostProduction", "TextOverlay", "v1"),
            TimeProvider.System);
    }

    public async Task<TextOverlayArtifact> ApplyAsync(
        FinalVideoArtifact source,
        CaptionOverlayPlanResponseRecord planResponse,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(source);
        ArgumentNullException.ThrowIfNull(planResponse);
        CaptionOverlayPlanParser.Validate(planResponse);
        var plan = planResponse.Plan;
        if (!string.Equals(plan.ProductionJobId, source.ProductionJobId, StringComparison.Ordinal))
        {
            throw new TextOverlayException(TextOverlayException.SourceInvalid);
        }

        var sourcePath = await VerifySourceAsync(source, cancellationToken).ConfigureAwait(false);
        if (!plan.OverlaysRequired)
        {
            // 空计划：不调用 ffmpeg、不复制、不重编码；直接引用已验证的 C004 源。
            return new TextOverlayArtifact(
                source.ProductionJobId,
                source.Sha256,
                planResponse.CaptionOverlayPlanDigest,
                plan.OutputProfileId,
                sourcePath,
                null,
                source.Sha256,
                source.Bytes,
                Passthrough: true,
                Reused: false);
        }

        var cues = WindowsCaptionOverlayRenderer.PrepareCues(plan, _fonts);
        var identity = ArtifactIdentity(source, planResponse, cues);
        var stem = $"overlay-{identity[..32]}";
        var root = Path.GetFullPath(_overlayRootResolver());
        Directory.CreateDirectory(root);
        ProductionLocalEnvironment.AssertNoLinkEscape(root, root);
        var outputName = stem + ".mp4";
        var manifestName = stem + ".text-overlay.json";
        var outputPath = ProductionLocalEnvironment.ResolveUnderRoot(root, outputName, requireExistingFile: false);
        var manifestPath = ProductionLocalEnvironment.ResolveUnderRoot(root, manifestName, requireExistingFile: false);

        if (File.Exists(outputPath) || File.Exists(manifestPath) || Directory.Exists(outputPath))
        {
            return await ReuseAsync(
                source, planResponse, identity, root, outputPath, manifestPath, outputName, cancellationToken)
                .ConfigureAwait(false);
        }

        var workDirectory = ProductionLocalEnvironment.ResolveUnderRoot(
            root,
            Path.Combine(".work", Guid.NewGuid().ToString("N")),
            requireExistingFile: false);
        Directory.CreateDirectory(workDirectory);
        ProductionLocalEnvironment.AssertNoLinkEscape(root, workDirectory);
        var manifestPartial = ProductionLocalEnvironment.ResolveUnderRoot(
            root, $".{manifestName}.{Guid.NewGuid():N}.partial", requireExistingFile: false);
        try
        {
            var (renderedName, _) = await _renderer.RenderAsync(sourcePath, workDirectory, plan, cues, cancellationToken)
                .ConfigureAwait(false);
            var renderedPath = Path.Combine(workDirectory, renderedName);
            var bytes = new FileInfo(renderedPath).Length;
            var sha256 = await ProductionLocalEnvironment.Sha256FileAsync(renderedPath, cancellationToken)
                .ConfigureAwait(false);

            // 先落输出，再以清单作为提交标记；两者都用原子 Move，绝不覆盖。
            File.Move(renderedPath, outputPath, overwrite: false);
            var manifest = BuildManifest(source, planResponse, identity, cues, outputName, sha256, bytes);
            await File.WriteAllTextAsync(
                manifestPartial,
                JsonSerializer.Serialize(manifest),
                new UTF8Encoding(false),
                cancellationToken).ConfigureAwait(false);
            File.Move(manifestPartial, manifestPath, overwrite: false);
            return new TextOverlayArtifact(
                source.ProductionJobId,
                source.Sha256,
                planResponse.CaptionOverlayPlanDigest,
                plan.OutputProfileId,
                outputPath,
                manifestPath,
                sha256,
                bytes,
                Passthrough: false,
                Reused: false);
        }
        catch (IOException exception)
        {
            throw new TextOverlayException(TextOverlayException.ArtifactConflict, exception);
        }
        finally
        {
            TryDeleteFile(manifestPartial);
            TryDeleteDirectory(workDirectory);
        }
    }

    /// <summary>源必须是 C004 托管根下的普通文件，并且字节数与 SHA-256 重新计算后一致。</summary>
    private async Task<string> VerifySourceAsync(FinalVideoArtifact source, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(source.FilePath)
            || string.IsNullOrWhiteSpace(source.ProductionJobId)
            || source.Sha256 is not { Length: 64 }
            || !source.Sha256.All(static ch => ch is (>= '0' and <= '9') or (>= 'a' and <= 'f'))
            || source.Bytes <= 0)
        {
            throw new TextOverlayException(TextOverlayException.SourceInvalid);
        }
        try
        {
            var finalRoot = Path.GetFullPath(_finalRootResolver());
            if (!Directory.Exists(finalRoot))
            {
                throw new TextOverlayException(TextOverlayException.SourceInvalid);
            }
            ProductionLocalEnvironment.AssertNoLinkEscape(finalRoot, finalRoot);
            var identity = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(source.ProductionJobId)))
                .ToLowerInvariant()[..32];
            var fullPath = Path.GetFullPath(source.FilePath);
            var expected = ProductionLocalEnvironment.ResolveUnderRoot(
                finalRoot, $"final-{identity}.mp4", requireExistingFile: false);
            if (!string.Equals(fullPath, expected, StringComparison.OrdinalIgnoreCase))
            {
                throw new TextOverlayException(TextOverlayException.SourceInvalid);
            }
            ProductionLocalEnvironment.AssertNoLinkEscape(finalRoot, fullPath);
            if (!ProductionLocalEnvironment.IsOrdinaryFile(fullPath)
                || new FileInfo(fullPath).Length != source.Bytes)
            {
                throw new TextOverlayException(TextOverlayException.SourceInvalid);
            }
            var actual = await ProductionLocalEnvironment.Sha256FileAsync(fullPath, cancellationToken)
                .ConfigureAwait(false);
            if (!string.Equals(actual, source.Sha256, StringComparison.Ordinal))
            {
                throw new TextOverlayException(TextOverlayException.SourceInvalid);
            }
            return fullPath;
        }
        catch (Exception exception) when (exception is InvalidDataException
            or IOException
            or UnauthorizedAccessException
            or ArgumentException
            or NotSupportedException)
        {
            throw new TextOverlayException(TextOverlayException.SourceInvalid, exception);
        }
    }

    /// <summary>身份绑定：C004 源 SHA + 计划 digest + 渲染档位 + 已解析字体身份。</summary>
    private static string ArtifactIdentity(
        FinalVideoArtifact source,
        CaptionOverlayPlanResponseRecord response,
        IReadOnlyList<PreparedOverlayCue> cues)
    {
        var fonts = new JsonArray();
        foreach (var identity in cues.Select(static cue => cue.Font.IdentitySha256)
                     .Distinct(StringComparer.Ordinal)
                     .Order(StringComparer.Ordinal))
        {
            fonts.Add(identity);
        }
        var node = new JsonObject
        {
            ["renderer_profile_id"] = WindowsCaptionOverlayRenderer.RendererProfileId,
            ["source_final_sha256"] = source.Sha256,
            ["caption_overlay_plan_digest"] = response.CaptionOverlayPlanDigest,
            ["output_profile_id"] = response.Plan.OutputProfileId,
            ["overlay_style_profile_id"] = response.Plan.OverlayStyleProfileId,
            ["font_profile_id"] = response.Plan.FontProfileId,
            ["font_identity_sha256"] = fonts,
        };
        return Convert.ToHexString(SHA256.HashData(CanonicalJson.Serialize(node))).ToLowerInvariant();
    }

    private TextOverlayManifest BuildManifest(
        FinalVideoArtifact source,
        CaptionOverlayPlanResponseRecord response,
        string identity,
        IReadOnlyList<PreparedOverlayCue> cues,
        string outputName,
        string outputSha256,
        long outputBytes) =>
        new(
            ManifestSchemaVersion,
            source.ProductionJobId,
            source.ProductionPackageId,
            source.ProductionPackageDigest,
            source.Sha256,
            response.CaptionOverlayPlanDigest,
            response.Plan.OutputProfileId,
            response.Plan.OverlayStyleProfileId,
            response.Plan.FontProfileId,
            WindowsCaptionOverlayRenderer.RendererProfileId,
            identity,
            cues.Select(static cue => new TextOverlayManifestCue(
                cue.Cue.CueId,
                cue.Cue.BeatId,
                cue.Cue.Order,
                cue.Cue.TextSha256,
                cue.Cue.StartMs,
                cue.Cue.EndMs,
                cue.Font.FileName,
                cue.Font.IdentitySha256)).ToList(),
            outputName,
            outputSha256,
            outputBytes,
            false,
            _timeProvider.GetUtcNow());

    /// <summary>清单+输出逐项重验；任何缺失、不一致、被篡改都 fail closed，且绝不覆盖。</summary>
    private async Task<TextOverlayArtifact> ReuseAsync(
        FinalVideoArtifact source,
        CaptionOverlayPlanResponseRecord response,
        string identity,
        string root,
        string outputPath,
        string manifestPath,
        string outputName,
        CancellationToken cancellationToken)
    {
        try
        {
            ProductionLocalEnvironment.AssertNoLinkEscape(root, outputPath);
            ProductionLocalEnvironment.AssertNoLinkEscape(root, manifestPath);
            if (!ProductionLocalEnvironment.IsOrdinaryFile(outputPath)
                || !ProductionLocalEnvironment.IsOrdinaryFile(manifestPath)
                || new FileInfo(manifestPath).Length > 256 * 1024)
            {
                throw new TextOverlayException(TextOverlayException.ArtifactConflict);
            }
            var manifest = JsonSerializer.Deserialize<TextOverlayManifest>(
                await File.ReadAllTextAsync(manifestPath, cancellationToken).ConfigureAwait(false),
                ManifestJson)
                ?? throw new TextOverlayException(TextOverlayException.ArtifactConflict);
            if (manifest.SchemaVersion != ManifestSchemaVersion
                || manifest.ProductionJobId != source.ProductionJobId
                || manifest.ProductionPackageId != source.ProductionPackageId
                || manifest.ProductionPackageDigest != source.ProductionPackageDigest
                || manifest.SourceFinalSha256 != source.Sha256
                || manifest.CaptionOverlayPlanDigest != response.CaptionOverlayPlanDigest
                || manifest.OutputProfileId != response.Plan.OutputProfileId
                || manifest.RendererProfileId != WindowsCaptionOverlayRenderer.RendererProfileId
                || manifest.ArtifactIdentitySha256 != identity
                || manifest.OutputFileName != outputName
                || manifest.Passthrough
                || manifest.OutputBytes <= 0
                || new FileInfo(outputPath).Length != manifest.OutputBytes)
            {
                throw new TextOverlayException(TextOverlayException.ArtifactConflict);
            }
            var actual = await ProductionLocalEnvironment.Sha256FileAsync(outputPath, cancellationToken)
                .ConfigureAwait(false);
            if (!string.Equals(actual, manifest.OutputSha256, StringComparison.Ordinal))
            {
                throw new TextOverlayException(TextOverlayException.ArtifactConflict);
            }
            return new TextOverlayArtifact(
                source.ProductionJobId,
                source.Sha256,
                response.CaptionOverlayPlanDigest,
                response.Plan.OutputProfileId,
                outputPath,
                manifestPath,
                actual,
                manifest.OutputBytes,
                Passthrough: false,
                Reused: true);
        }
        catch (Exception exception) when (exception is InvalidDataException
            or IOException
            or UnauthorizedAccessException
            or JsonException)
        {
            throw new TextOverlayException(TextOverlayException.ArtifactConflict, exception);
        }
    }

    private static void TryDeleteFile(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (IOException)
        {
            // 暂存文件位于托管根的隐藏名下，清理失败无害。
        }
        catch (UnauthorizedAccessException)
        {
            // 同上。
        }
    }

    private static void TryDeleteDirectory(string path)
    {
        try
        {
            if (Directory.Exists(path))
            {
                Directory.Delete(path, recursive: true);
            }
        }
        catch (IOException)
        {
            // 同上。
        }
        catch (UnauthorizedAccessException)
        {
            // 同上。
        }
    }

    private sealed record TextOverlayManifestCue(
        [property: JsonPropertyName("cue_id")] string CueId,
        [property: JsonPropertyName("beat_id")] string BeatId,
        [property: JsonPropertyName("order")] int Order,
        [property: JsonPropertyName("text_sha256")] string TextSha256,
        [property: JsonPropertyName("start_ms")] int StartMs,
        [property: JsonPropertyName("end_ms")] int EndMs,
        [property: JsonPropertyName("resolved_font_name")] string ResolvedFontName,
        [property: JsonPropertyName("resolved_font_identity_sha256")] string ResolvedFontIdentitySha256);

    private sealed record TextOverlayManifest(
        [property: JsonPropertyName("schema_version")] string SchemaVersion,
        [property: JsonPropertyName("production_job_id")] string ProductionJobId,
        [property: JsonPropertyName("source_production_package_id")] string ProductionPackageId,
        [property: JsonPropertyName("source_production_package_digest")] string ProductionPackageDigest,
        [property: JsonPropertyName("source_final_sha256")] string SourceFinalSha256,
        [property: JsonPropertyName("caption_overlay_plan_digest")] string CaptionOverlayPlanDigest,
        [property: JsonPropertyName("output_profile_id")] string OutputProfileId,
        [property: JsonPropertyName("overlay_style_profile_id")] string OverlayStyleProfileId,
        [property: JsonPropertyName("font_profile_id")] string FontProfileId,
        [property: JsonPropertyName("renderer_profile_id")] string RendererProfileId,
        [property: JsonPropertyName("artifact_identity_sha256")] string ArtifactIdentitySha256,
        [property: JsonPropertyName("cues")] IReadOnlyList<TextOverlayManifestCue> Cues,
        [property: JsonPropertyName("output_file_name")] string OutputFileName,
        [property: JsonPropertyName("output_sha256")] string OutputSha256,
        [property: JsonPropertyName("output_bytes")] long OutputBytes,
        [property: JsonPropertyName("passthrough")] bool Passthrough,
        [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);
}
