using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
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
            || !string.Equals(
                ComputeDigest(plan),
                response.NarrationPlanDigest,
                StringComparison.Ordinal)
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

    public static string ComputeDigest(NarrationPlanRecord plan)
    {
        ArgumentNullException.ThrowIfNull(plan);
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(
            stream,
            new JsonWriterOptions
            {
                Indented = false,
                Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            }))
        {
            writer.WriteStartObject();
            writer.WriteString("creative_package_digest", plan.CreativePackageDigest);
            writer.WriteString("creative_package_id", plan.CreativePackageId);
            writer.WriteBoolean("narration_required", plan.NarrationRequired);
            writer.WriteString("production_job_id", plan.ProductionJobId);
            writer.WriteString("production_plan_digest", plan.ProductionPlanDigest);
            writer.WriteString("schema_version", plan.SchemaVersion);
            writer.WritePropertyName("segments");
            writer.WriteStartArray();
            foreach (var segment in plan.Segments)
            {
                writer.WriteStartObject();
                writer.WriteString("beat_id", segment.BeatId);
                writer.WriteNumber("end_ms", segment.EndMs);
                writer.WriteNumber("order", segment.Order);
                writer.WriteString("segment_id", segment.SegmentId);
                writer.WriteNumber("start_ms", segment.StartMs);
                writer.WriteString("text", segment.Text);
                writer.WriteString("text_sha256", segment.TextSha256);
                writer.WriteEndObject();
            }
            writer.WriteEndArray();
            writer.WriteNumber("target_runtime_ms", plan.TargetRuntimeMs);
            writer.WriteString("tts_profile_id", plan.TtsProfileId);
            writer.WriteString("voice_profile_id", plan.VoiceProfileId);
            writer.WriteEndObject();
        }
        return Convert.ToHexString(SHA256.HashData(stream.ToArray())).ToLowerInvariant();
    }

    private static bool Bounded(string? value, int maximum) =>
        value is { Length: > 0 } && value.Length <= maximum;

    private static bool Digest(string? value) =>
        value is { Length: 64 } && value.All(character =>
            character is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static string HashText(string value) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();
}
