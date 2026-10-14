using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using PicotooPet.Desktop.Core.Contracts;

[assembly: InternalsVisibleTo("PicotooPet.FinalVideoQa.SmokeTests")]

namespace PicotooPet.Desktop.Services;

public sealed record FinalVideoQaInputV1(
    GoalVideoContinuationRecord GoalContinuation,
    ProductionJobRecord ProductionJob,
    ProductionPlanRecord ProductionPlan,
    ProductionPackageRecord ProductionPackage,
    MasterCompositionInputV1 MasterInput,
    MasterVideoArtifact? MasterArtifact);

public sealed class FinalVideoQaException : Exception
{
    internal FinalVideoQaException(string suffix) : base("FINAL_QA_" + suffix) => Code = Message;
    public string Code { get; }
}

public sealed record FinalVideoQaResult(FinalArtifactReceiptV1 Receipt, string ReceiptPath, bool Reused);
public sealed record FinalQaVideoFacts(int Index, string CodecName, string PixelFormat, int Width, int Height,
    long FpsNumerator, long FpsDenominator, long DurationUs, long? PacketCount);
public sealed record FinalQaAudioFacts(int Index, string CodecName, string Profile, int SampleRate,
    int Channels, string? ChannelLayout, long DurationUs);
public sealed record FinalQaObservedMedia(string ContainerFamily, long FormatDurationUs, int StreamCount,
    FinalQaVideoFacts Video, FinalQaAudioFacts? Audio);

/// <summary>Only verified identities and neutral media facts; no text, path or process diagnostics.</summary>
public sealed record FinalArtifactReceiptV1(
    string SchemaVersion, string QaProfileId, string QaInputDigest, string ReceiptDigest, string Outcome,
    string GoalId, string HandoffSha256, string ReturnSha256, string CreativeJobId,
    string CreativePackageId, string CreativePackageDigest,
    string ProductionJobId, string ProductionPlanDigest, string ProductionPackageId,
    string ProductionPackageDigest, long TargetRuntimeMs, string OutputProfileId,
    bool NarrationRequired, string NarrationPlanDigest, string? NarrationManifestSha256,
    IReadOnlyList<MasterNarrationSegmentIdentity> NarrationSegments,
    bool CaptionsRequired, bool OverlaysRequired, string CaptionOverlayPlanDigest,
    string? C008bArtifactSha256, long? C008bArtifactBytes, string? C008bManifestSha256,
    string C004ManifestSha256, string C004SourceSha256, long C004SourceBytes,
    string CandidateKind, string ArtifactRootProfileId, string SelectedVisualKind,
    string SelectedVisualSha256, long SelectedVisualBytes,
    string? MasterProfileId, string? VideoProfileId, string? AudioProfileId,
    string? MasterInputDigest, string? MasterManifestSha256,
    string ArtifactFileName, string ArtifactSha256, long ArtifactBytes,
    FinalQaObservedMedia ObservedMedia, IReadOnlyList<string> PassedCheckIds, DateTimeOffset VerifiedAt);

internal static class FinalQaIdentity
{
    internal const string Profile = "final-video.qa.windows.v1";
    internal const long ContainerTimestampBudgetUs = 100_000;
    internal static readonly IReadOnlyList<string> Checks = Array.AsReadOnly<string>(["lineage.v1", "managed-file.v1", "sha-bytes.v1", "mp4-probe.v1",
        "full-decode.v1", "video-stream.v1", "output-profile.v1", "runtime.v1", "audio-contract.v1",
        "unexpected-streams.v1", "overlay-provenance.v1"]);
    internal static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        RespectRequiredConstructorParameters = true,
        RespectNullableAnnotations = true,
        MaxDepth = 32,
    };
    internal static string Hash(JsonNode node) => Convert.ToHexString(SHA256.HashData(CanonicalJson.Serialize(node))).ToLowerInvariant();
    internal static string ReceiptDigest(FinalArtifactReceiptV1 receipt)
    {
        var node = JsonSerializer.SerializeToNode(receipt, Json)!.AsObject();
        node.Remove("receipt_digest");
        node.Remove("verified_at");
        return Hash(node);
    }
    internal static bool Sha(string? value) => value is { Length: 64 }
        && value.All(c => c is (>= '0' and <= '9') or (>= 'a' and <= 'f'));
}
