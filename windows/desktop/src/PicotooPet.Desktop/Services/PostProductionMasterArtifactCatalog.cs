using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Services;

/// <summary>只查询期望 job 与 digest 的精确目录；缺损、篡改或额外条目一律冲突。</summary>
public sealed class PostProductionMasterArtifactCatalog
{
    internal const string OutputFileName = "master.mp4";
    internal const string ManifestFileName = "master-manifest.json";
    private const int MaximumManifestBytes = 512 * 1024;
    private static readonly JsonSerializerOptions StrictJson = new()
    {
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };
    private readonly string _root;

    public PostProductionMasterArtifactCatalog(string managedRoot)
    {
        if (string.IsNullOrWhiteSpace(managedRoot) || !Path.IsPathFullyQualified(managedRoot))
        {
            throw new ArgumentException(MasterCompositionException.InputInvalid, nameof(managedRoot));
        }
        _root = Path.GetFullPath(managedRoot);
    }

    public async Task<MasterVideoArtifact?> FindVerifiedExactAsync(
        MasterArtifactExpectation expected,
        CancellationToken cancellationToken = default)
    {
        try
        {
            ArgumentNullException.ThrowIfNull(expected);
            if (!IsSha(expected.MasterInputDigest)
                || MasterInputIdentity.Compute(expected.Identity) != expected.MasterInputDigest)
            {
                throw Conflict();
            }
            if (!Directory.Exists(_root))
            {
                return null;
            }
            ProductionLocalEnvironment.AssertNoLinkEscape(_root, _root);
            var jobDirectory = MasterPathPolicy.JobDirectory(_root, expected.Identity.ProductionJobId);
            if (File.Exists(jobDirectory))
            {
                throw Conflict();
            }
            if (!Directory.Exists(jobDirectory))
            {
                return null;
            }
            ProductionLocalEnvironment.AssertNoLinkEscape(_root, jobDirectory);
            var artifactDirectory = MasterPathPolicy.ArtifactDirectory(jobDirectory, expected.MasterInputDigest);
            if (File.Exists(artifactDirectory))
            {
                throw Conflict();
            }
            if (!Directory.Exists(artifactDirectory))
            {
                return null;
            }
            ProductionLocalEnvironment.AssertNoLinkEscape(_root, artifactDirectory);
            var entries = Directory.EnumerateFileSystemEntries(artifactDirectory).ToArray();
            if (entries.Length != 2)
            {
                throw Conflict();
            }
            var outputPath = Path.Combine(artifactDirectory, OutputFileName);
            var manifestPath = Path.Combine(artifactDirectory, ManifestFileName);
            if (!entries.Any(path => SamePath(path, outputPath))
                || !entries.Any(path => SamePath(path, manifestPath))
                || !ProductionLocalEnvironment.IsOrdinaryFile(outputPath)
                || !ProductionLocalEnvironment.IsOrdinaryFile(manifestPath))
            {
                throw Conflict();
            }
            ProductionLocalEnvironment.AssertNoLinkEscape(_root, outputPath);
            ProductionLocalEnvironment.AssertNoLinkEscape(_root, manifestPath);
            var manifestLength = new FileInfo(manifestPath).Length;
            if (manifestLength is <= 0 or > MaximumManifestBytes)
            {
                throw Conflict();
            }
            var manifestBytes = await File.ReadAllBytesAsync(manifestPath, cancellationToken).ConfigureAwait(false);
            var manifest = JsonSerializer.Deserialize<MasterManifest>(manifestBytes, StrictJson) ?? throw Conflict();
            var outputBytes = new FileInfo(outputPath).Length;
            if (outputBytes <= 0)
            {
                throw Conflict();
            }
            var outputSha = await ProductionLocalEnvironment.Sha256FileAsync(outputPath, cancellationToken)
                .ConfigureAwait(false);
            if (!ManifestMatches(manifest, expected, outputSha, outputBytes))
            {
                throw Conflict();
            }
            return new MasterVideoArtifact(
                expected.Identity.ProductionJobId,
                expected.Identity.ProductionPackageId,
                expected.Identity.ProductionPackageDigest,
                expected.Identity.ProductionPlanDigest,
                expected.MasterInputDigest,
                expected.Identity.OutputProfileId,
                expected.Identity.TargetRuntimeMs,
                outputPath,
                manifestPath,
                outputSha,
                outputBytes,
                expected.Identity.NarrationRequired,
                expected.Identity.SelectedVisualKind,
                Reused: true);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (MasterCompositionException)
        {
            throw;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException
            or JsonException or ArgumentException or NotSupportedException or CryptographicException
            or OverflowException or NullReferenceException)
        {
            throw Conflict(exception);
        }
    }

    internal string Root => _root;

    private static bool ManifestMatches(
        MasterManifest manifest,
        MasterArtifactExpectation expected,
        string outputSha,
        long outputBytes)
    {
        var identity = expected.Identity;
        return manifest.SchemaVersion == PostProductionMasterProfiles.SchemaVersion
            && manifest.MasterProfileId == PostProductionMasterProfiles.MasterProfileId
            && manifest.VideoProfileId == PostProductionMasterProfiles.VideoProfileId
            && manifest.AudioProfileId == PostProductionMasterProfiles.AudioProfileId
            && manifest.ProductionJobId == identity.ProductionJobId
            && manifest.ProductionPackageId == identity.ProductionPackageId
            && manifest.ProductionPackageDigest == identity.ProductionPackageDigest
            && manifest.CreativePackageId == identity.CreativePackageId
            && manifest.CreativePackageDigest == identity.CreativePackageDigest
            && manifest.ProductionPlanDigest == identity.ProductionPlanDigest
            && manifest.TargetRuntimeMs == identity.TargetRuntimeMs
            && manifest.OutputProfileId == identity.OutputProfileId
            && manifest.NarrationRequired == identity.NarrationRequired
            && manifest.NarrationPlanDigest == identity.NarrationPlanDigest
            && manifest.NarrationManifestSha256 == identity.NarrationManifestSha256
            && SegmentsMatch(manifest.NarrationSegments, identity.NarrationSegments)
            && manifest.OverlaysRequired == identity.OverlaysRequired
            && manifest.CaptionOverlayPlanDigest == identity.CaptionOverlayPlanDigest
            && manifest.C004SourceSha256 == identity.C004SourceSha256
            && manifest.C004SourceBytes == identity.C004SourceBytes
            && manifest.SelectedVisualKind == identity.SelectedVisualKind
            && manifest.SelectedVisualSha256 == identity.SelectedVisualSha256
            && manifest.SelectedVisualBytes == identity.SelectedVisualBytes
            && manifest.C008BArtifactSha256 == identity.C008BArtifactSha256
            && manifest.C008BArtifactBytes == identity.C008BArtifactBytes
            && manifest.C008BManifestSha256 == identity.C008BManifestSha256
            && manifest.OutputFileName == OutputFileName
            && manifest.OutputSha256 == outputSha
            && manifest.OutputBytes == outputBytes
            && manifest.HasAudio == identity.NarrationRequired
            && manifest.MasterInputDigest == expected.MasterInputDigest
            && manifest.CreatedAt != default;
    }

    private static bool SegmentsMatch(
        IReadOnlyList<MasterManifestNarrationSegment> durable,
        IReadOnlyList<MasterNarrationSegmentIdentity> expected)
    {
        if (durable.Count != expected.Count)
        {
            return false;
        }
        for (var index = 0; index < expected.Count; index++)
        {
            var left = durable[index];
            var right = expected[index];
            if (left.SegmentId != right.SegmentId || left.BeatId != right.BeatId
                || left.Order != right.Order || left.TextSha256 != right.TextSha256
                || left.StartMs != right.StartMs || left.EndMs != right.EndMs
                || left.WavSha256 != right.WavSha256 || left.WavBytes != right.WavBytes
                || left.ActualDurationMs != right.ActualDurationMs
                || left.SampleFrames != right.SampleFrames || left.SampleRate != right.SampleRate
                || left.Channels != right.Channels || left.BitsPerSample != right.BitsPerSample)
            {
                return false;
            }
        }
        return true;
    }

    private static bool SamePath(string left, string right) =>
        string.Equals(Path.GetFullPath(left), Path.GetFullPath(right), StringComparison.OrdinalIgnoreCase);

    private static bool IsSha(string? value) => value is { Length: 64 }
        && value.All(static character => character is (>= '0' and <= '9') or (>= 'a' and <= 'f'));

    private static MasterCompositionException Conflict(Exception? inner = null) =>
        new(MasterCompositionException.ArtifactConflict, inner);
}

internal static class MasterPathPolicy
{
    public static string JobDirectory(string root, string productionJobId)
    {
        if (string.IsNullOrWhiteSpace(productionJobId) || productionJobId.Length > 120)
        {
            throw new MasterCompositionException(MasterCompositionException.InputInvalid);
        }
        var safe = new string(productionJobId.Select(character => char.IsAsciiLetterOrDigit(character)
            || character is '-' or '_' ? character : '_').Take(40).ToArray());
        var suffix = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(productionJobId)))
            .ToLowerInvariant()[..16];
        return ProductionLocalEnvironment.ResolveUnderRoot(root, $"{safe}-{suffix}", requireExistingFile: false);
    }

    public static string ArtifactDirectory(string jobDirectory, string digest)
    {
        if (digest is not { Length: 64 }
            || digest.Any(static character => character is not (>= '0' and <= '9' or >= 'a' and <= 'f')))
        {
            throw new MasterCompositionException(MasterCompositionException.InputInvalid);
        }
        return ProductionLocalEnvironment.ResolveUnderRoot(jobDirectory, digest, requireExistingFile: false);
    }
}

internal sealed record MasterManifestNarrationSegment(
    [property: JsonPropertyName("segment_id")] string SegmentId,
    [property: JsonPropertyName("beat_id")] string BeatId,
    [property: JsonPropertyName("order")] int Order,
    [property: JsonPropertyName("text_sha256")] string TextSha256,
    [property: JsonPropertyName("start_ms")] long StartMs,
    [property: JsonPropertyName("end_ms")] long EndMs,
    [property: JsonPropertyName("wav_sha256")] string WavSha256,
    [property: JsonPropertyName("wav_bytes")] long WavBytes,
    [property: JsonPropertyName("actual_duration_ms")] long ActualDurationMs,
    [property: JsonPropertyName("sample_frames")] long SampleFrames,
    [property: JsonPropertyName("sample_rate")] int SampleRate,
    [property: JsonPropertyName("channels")] short Channels,
    [property: JsonPropertyName("bits_per_sample")] short BitsPerSample);

internal sealed record MasterManifest(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("master_profile_id")] string MasterProfileId,
    [property: JsonPropertyName("video_profile_id")] string VideoProfileId,
    [property: JsonPropertyName("audio_profile_id")] string AudioProfileId,
    [property: JsonPropertyName("production_job_id")] string ProductionJobId,
    [property: JsonPropertyName("production_package_id")] string ProductionPackageId,
    [property: JsonPropertyName("production_package_digest")] string ProductionPackageDigest,
    [property: JsonPropertyName("creative_package_id")] string CreativePackageId,
    [property: JsonPropertyName("creative_package_digest")] string CreativePackageDigest,
    [property: JsonPropertyName("production_plan_digest")] string ProductionPlanDigest,
    [property: JsonPropertyName("target_runtime_ms")] long TargetRuntimeMs,
    [property: JsonPropertyName("output_profile_id")] string OutputProfileId,
    [property: JsonPropertyName("narration_required")] bool NarrationRequired,
    [property: JsonPropertyName("narration_plan_digest")] string NarrationPlanDigest,
    [property: JsonPropertyName("narration_manifest_sha256")] string? NarrationManifestSha256,
    [property: JsonPropertyName("narration_segments")] IReadOnlyList<MasterManifestNarrationSegment> NarrationSegments,
    [property: JsonPropertyName("overlays_required")] bool OverlaysRequired,
    [property: JsonPropertyName("caption_overlay_plan_digest")] string CaptionOverlayPlanDigest,
    [property: JsonPropertyName("c004_source_sha256")] string C004SourceSha256,
    [property: JsonPropertyName("c004_source_bytes")] long C004SourceBytes,
    [property: JsonPropertyName("selected_visual_kind")] string SelectedVisualKind,
    [property: JsonPropertyName("selected_visual_sha256")] string SelectedVisualSha256,
    [property: JsonPropertyName("selected_visual_bytes")] long SelectedVisualBytes,
    [property: JsonPropertyName("c008b_artifact_sha256")] string? C008BArtifactSha256,
    [property: JsonPropertyName("c008b_artifact_bytes")] long? C008BArtifactBytes,
    [property: JsonPropertyName("c008b_manifest_sha256")] string? C008BManifestSha256,
    [property: JsonPropertyName("output_file_name")] string OutputFileName,
    [property: JsonPropertyName("output_sha256")] string OutputSha256,
    [property: JsonPropertyName("output_bytes")] long OutputBytes,
    [property: JsonPropertyName("has_audio")] bool HasAudio,
    [property: JsonPropertyName("master_input_digest")] string MasterInputDigest,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);
