using System.Security.Cryptography;
using System.Text.Json;

namespace PicotooPet.Desktop.Services;

/// <summary>C009A 冻结的主片档位、身份、产物与封闭错误合同。</summary>
public static class PostProductionMasterProfiles
{
    public const string SchemaVersion = "1.0";
    public const string MasterProfileId = "postproduction.master.v1";
    public const string VideoProfileId = "video.h264.stream-copy.v1";
    public const string AudioProfileId = "audio.aac-lc.48k.mono.128k.v1";
    public const string C004VisualKind = "c004_final_v1";
    public const string C008BVisualKind = "c008b_overlay_v1";
}

public sealed class MasterCompositionException : Exception
{
    public const string InputInvalid = "MASTER_INPUT_INVALID";
    public const string LineageMismatch = "MASTER_LINEAGE_MISMATCH";
    public const string VisualInvalid = "MASTER_VISUAL_INVALID";
    public const string NarrationInvalid = "MASTER_NARRATION_INVALID";
    public const string NarrationSegmentTooLong = "NARRATION_SEGMENT_TOO_LONG";
    public const string ArtifactConflict = "MASTER_ARTIFACT_CONFLICT";
    public const string ComposerFailed = "MASTER_COMPOSER_FAILED";
    public const string OutputInvalid = "MASTER_OUTPUT_INVALID";

    public MasterCompositionException(string code, Exception? innerException = null)
        : base(code, innerException) => Code = code;

    public string Code { get; }
}

public sealed record MasterCompositionInputV1(
    FinalVideoArtifact C004,
    PicotooPet.Desktop.Core.Contracts.NarrationPlanResponseRecord NarrationPlan,
    NarrationArtifact? NarrationArtifact,
    PicotooPet.Desktop.Core.Contracts.CaptionOverlayPlanResponseRecord OverlayPlan,
    TextOverlayArtifact? OverlayArtifact);

public sealed record MasterCompositionResult(
    bool Required,
    FinalVideoArtifact? C004Fallback,
    MasterVideoArtifact? Artifact);

public sealed record MasterVideoArtifact(
    string ProductionJobId,
    string ProductionPackageId,
    string ProductionPackageDigest,
    string ProductionPlanDigest,
    string MasterInputDigest,
    string OutputProfileId,
    long TargetRuntimeMs,
    string FilePath,
    string ManifestPath,
    string Sha256,
    long Bytes,
    bool HasAudio,
    string VisualSourceKind,
    bool Reused);

public sealed record VerifiedMasterVisual(
    string Path,
    string Sha256,
    long Bytes,
    string SourceKind);

public sealed record VerifiedMasterNarrationSegment(
    string SegmentId,
    int Order,
    string WavPath,
    string Sha256,
    long Bytes,
    long StartMs,
    long EndMs,
    long ActualDurationMs,
    long SampleFrames,
    int SampleRate,
    short Channels);

public sealed record MasterNarrationSegmentIdentity(
    string SegmentId,
    string BeatId,
    int Order,
    string TextSha256,
    long StartMs,
    long EndMs,
    string WavSha256,
    long WavBytes,
    long ActualDurationMs,
    long SampleFrames,
    int SampleRate,
    short Channels,
    short BitsPerSample);

public sealed record MasterIdentityFacts(
    string ProductionJobId,
    string ProductionPackageId,
    string ProductionPackageDigest,
    string ProductionPlanDigest,
    string CreativePackageId,
    string CreativePackageDigest,
    long TargetRuntimeMs,
    string OutputProfileId,
    bool NarrationRequired,
    string NarrationPlanDigest,
    string? NarrationManifestSha256,
    IReadOnlyList<MasterNarrationSegmentIdentity> NarrationSegments,
    bool OverlaysRequired,
    string CaptionOverlayPlanDigest,
    string SelectedVisualKind,
    string SelectedVisualSha256,
    long SelectedVisualBytes,
    string C004SourceSha256,
    long C004SourceBytes,
    string? C008BArtifactSha256,
    long? C008BArtifactBytes,
    string? C008BManifestSha256);

public sealed record MasterArtifactExpectation(
    MasterIdentityFacts Identity,
    string MasterInputDigest);

internal static class MasterInputIdentity
{
    public static string Compute(MasterIdentityFacts facts)
    {
        ArgumentNullException.ThrowIfNull(facts);
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = false }))
        {
            writer.WriteStartObject();
            writer.WriteString("audio_profile_id", PostProductionMasterProfiles.AudioProfileId);
            writer.WriteNumber("c004_source_bytes", facts.C004SourceBytes);
            writer.WriteString("c004_source_sha256", facts.C004SourceSha256);
            if (facts.C008BArtifactBytes is long c008Bytes)
            {
                writer.WriteNumber("c008b_artifact_bytes", c008Bytes);
            }
            else
            {
                writer.WriteNull("c008b_artifact_bytes");
            }
            WriteNullable(writer, "c008b_artifact_sha256", facts.C008BArtifactSha256);
            writer.WriteString("caption_overlay_plan_digest", facts.CaptionOverlayPlanDigest);
            writer.WriteString("creative_package_digest", facts.CreativePackageDigest);
            writer.WriteString("creative_package_id", facts.CreativePackageId);
            writer.WriteString("master_profile_id", PostProductionMasterProfiles.MasterProfileId);
            writer.WriteString("narration_plan_digest", facts.NarrationPlanDigest);
            writer.WriteBoolean("narration_required", facts.NarrationRequired);
            writer.WritePropertyName("narration_segments");
            writer.WriteStartArray();
            foreach (var segment in facts.NarrationSegments)
            {
                writer.WriteStartObject();
                writer.WriteNumber("actual_duration_ms", segment.ActualDurationMs);
                writer.WriteString("beat_id", segment.BeatId);
                writer.WriteNumber("bits_per_sample", segment.BitsPerSample);
                writer.WriteNumber("channels", segment.Channels);
                writer.WriteNumber("end_ms", segment.EndMs);
                writer.WriteNumber("order", segment.Order);
                writer.WriteNumber("sample_frames", segment.SampleFrames);
                writer.WriteNumber("sample_rate", segment.SampleRate);
                writer.WriteString("segment_id", segment.SegmentId);
                writer.WriteNumber("start_ms", segment.StartMs);
                writer.WriteString("text_sha256", segment.TextSha256);
                writer.WriteNumber("wav_bytes", segment.WavBytes);
                writer.WriteString("wav_sha256", segment.WavSha256);
                writer.WriteEndObject();
            }
            writer.WriteEndArray();
            writer.WriteString("output_profile_id", facts.OutputProfileId);
            writer.WriteBoolean("overlays_required", facts.OverlaysRequired);
            writer.WriteString("production_job_id", facts.ProductionJobId);
            writer.WriteString("production_package_digest", facts.ProductionPackageDigest);
            writer.WriteString("production_package_id", facts.ProductionPackageId);
            writer.WriteString("production_plan_digest", facts.ProductionPlanDigest);
            writer.WriteString("schema_version", PostProductionMasterProfiles.SchemaVersion);
            writer.WriteNumber("selected_visual_bytes", facts.SelectedVisualBytes);
            writer.WriteString("selected_visual_kind", facts.SelectedVisualKind);
            writer.WriteString("selected_visual_sha256", facts.SelectedVisualSha256);
            writer.WriteNumber("target_runtime_ms", facts.TargetRuntimeMs);
            writer.WriteString("video_profile_id", PostProductionMasterProfiles.VideoProfileId);
            writer.WriteEndObject();
        }
        return Convert.ToHexString(SHA256.HashData(stream.ToArray())).ToLowerInvariant();
    }

}
