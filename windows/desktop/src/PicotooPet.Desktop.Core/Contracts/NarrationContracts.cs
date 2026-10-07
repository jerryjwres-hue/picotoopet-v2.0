using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record NarrationSegmentPlanRecord(
    [property: JsonPropertyName("segment_id")] string SegmentId,
    [property: JsonPropertyName("beat_id")] string BeatId,
    [property: JsonPropertyName("order")] int Order,
    [property: JsonPropertyName("text")] string Text,
    [property: JsonPropertyName("text_sha256")] string TextSha256,
    [property: JsonPropertyName("start_ms")] long StartMs,
    [property: JsonPropertyName("end_ms")] long EndMs);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record NarrationPlanRecord(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("production_job_id")] string ProductionJobId,
    [property: JsonPropertyName("creative_package_id")] string CreativePackageId,
    [property: JsonPropertyName("creative_package_digest")] string CreativePackageDigest,
    [property: JsonPropertyName("production_plan_digest")] string ProductionPlanDigest,
    [property: JsonPropertyName("target_runtime_ms")] long TargetRuntimeMs,
    [property: JsonPropertyName("tts_profile_id")] string TtsProfileId,
    [property: JsonPropertyName("voice_profile_id")] string VoiceProfileId,
    [property: JsonPropertyName("narration_required")] bool NarrationRequired,
    [property: JsonPropertyName("segments")] NarrationSegmentPlanRecord[] Segments);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record NarrationPlanResponseRecord(
    [property: JsonPropertyName("plan")] NarrationPlanRecord Plan,
    [property: JsonPropertyName("narration_plan_digest")] string NarrationPlanDigest);

public sealed class NarrationPlanContractException : Exception
{
    public NarrationPlanContractException() : base("NARRATION_PLAN_INVALID")
    {
    }
}

public static class NarrationPlanContract
{
    public const string TtsProfileId = "narration.local.windows.v1";
    public const string VoiceProfileId = "voice.windows.default.v1";

    public static void Validate(NarrationPlanResponseRecord response)
    {
        if (response is null || response.Plan is null)
        {
            throw new NarrationPlanContractException();
        }
        var plan = response.Plan;
        if (plan.SchemaVersion != "1.0"
            || !Bounded(plan.ProductionJobId, 80)
            || !Bounded(plan.CreativePackageId, 80)
            || !Digest(plan.CreativePackageDigest)
            || !Digest(plan.ProductionPlanDigest)
            || !Digest(response.NarrationPlanDigest)
            || plan.TargetRuntimeMs is <= 0 or > 600_000
            || plan.TtsProfileId != TtsProfileId
            || plan.VoiceProfileId != VoiceProfileId
            || plan.Segments is null
            || plan.Segments.Length > 60
            || plan.NarrationRequired != (plan.Segments.Length > 0))
        {
            throw new NarrationPlanContractException();
        }

        long previousEnd = 0;
        foreach (var (segment, index) in plan.Segments.Select((value, index) => (value, index)))
        {
            if (segment is null
                || !Bounded(segment.SegmentId, 80)
                || !Bounded(segment.BeatId, 80)
                || segment.Order != index + 1
                || !Bounded(segment.Text, 2000)
                || !Digest(segment.TextSha256)
                || !string.Equals(HashText(segment.Text), segment.TextSha256, StringComparison.Ordinal)
                || segment.StartMs < previousEnd
                || segment.EndMs <= segment.StartMs
                || segment.EndMs > plan.TargetRuntimeMs)
            {
                throw new NarrationPlanContractException();
            }
            previousEnd = segment.EndMs;
        }
    }

    private static bool Bounded(string? value, int maximum) =>
        value is { Length: > 0 } && value.Length <= maximum;

    private static bool Digest(string? value) =>
        value is { Length: 64 } && value.All(character =>
            character is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static string HashText(string value) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();
}
