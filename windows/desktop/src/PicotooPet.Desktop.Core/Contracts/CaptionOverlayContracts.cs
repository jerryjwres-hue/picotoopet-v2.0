using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>C008B 本地错误码；消息永远是封闭码，不含文案、路径、滤镜串或 FFmpeg stderr。</summary>
public sealed class TextOverlayException : Exception
{
    public const string PlanInvalid = "TEXT_OVERLAY_PLAN_INVALID";
    public const string SourceInvalid = "TEXT_OVERLAY_SOURCE_INVALID";
    public const string FontUnavailable = "TEXT_OVERLAY_FONT_UNAVAILABLE";
    public const string GlyphMissing = "TEXT_OVERLAY_GLYPH_MISSING";
    public const string FfmpegUnavailable = "TEXT_OVERLAY_FFMPEG_UNAVAILABLE";
    public const string FfmpegFailed = "TEXT_OVERLAY_FFMPEG_FAILED";
    public const string FfmpegTimeout = "TEXT_OVERLAY_FFMPEG_TIMEOUT";
    public const string OutputInvalid = "TEXT_OVERLAY_OUTPUT_INVALID";
    public const string ArtifactConflict = "TEXT_OVERLAY_ARTIFACT_CONFLICT";

    public TextOverlayException(string code, Exception? innerException = null)
        : base(code, innerException)
    {
        Code = code;
    }

    public string Code { get; }
}

/// <summary>C008A2 单条叠加/字幕 cue；文本是 Windows 渲染所需的权威数据，但绝不进入日志或清单。</summary>
public sealed record CaptionOverlayCueRecord(
    [property: JsonPropertyName("cue_id")] string CueId,
    [property: JsonPropertyName("beat_id")] string BeatId,
    [property: JsonPropertyName("order")] int Order,
    [property: JsonPropertyName("cue_kind")] string CueKind,
    [property: JsonPropertyName("text")] string Text,
    [property: JsonPropertyName("text_sha256")] string TextSha256,
    [property: JsonPropertyName("start_ms")] int StartMs,
    [property: JsonPropertyName("end_ms")] int EndMs);

/// <summary>Core 冻结的 CaptionOverlayPlanV1 投影；严格字段，无渲染/路径/字体授权。</summary>
public sealed record CaptionOverlayPlanRecord(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("production_job_id")] string ProductionJobId,
    [property: JsonPropertyName("creative_package_id")] string CreativePackageId,
    [property: JsonPropertyName("creative_package_digest")] string CreativePackageDigest,
    [property: JsonPropertyName("production_plan_digest")] string ProductionPlanDigest,
    [property: JsonPropertyName("target_runtime_ms")] int TargetRuntimeMs,
    [property: JsonPropertyName("output_profile_id")] string OutputProfileId,
    [property: JsonPropertyName("caption_style_profile_id")] string CaptionStyleProfileId,
    [property: JsonPropertyName("overlay_style_profile_id")] string OverlayStyleProfileId,
    [property: JsonPropertyName("font_profile_id")] string FontProfileId,
    [property: JsonPropertyName("captions_required")] bool CaptionsRequired,
    [property: JsonPropertyName("overlays_required")] bool OverlaysRequired,
    [property: JsonPropertyName("captions")] IReadOnlyList<CaptionOverlayCueRecord> Captions,
    [property: JsonPropertyName("overlays")] IReadOnlyList<CaptionOverlayCueRecord> Overlays);

public sealed record CaptionOverlayPlanResponseRecord(
    [property: JsonPropertyName("plan")] CaptionOverlayPlanRecord Plan,
    [property: JsonPropertyName("caption_overlay_plan_digest")] string CaptionOverlayPlanDigest);

/// <summary>C008B 冻结常量；调用方不能选择样式、字体或滤镜。</summary>
public static class CaptionOverlayConstants
{
    public const string OverlayStyleProfileId = "overlay.title-safe.v1";
    public const string CaptionStyleProfileId = "caption.lower-third.v1";
    public const string FontProfileId = "font.windows-system-sans.v1";
    public static readonly IReadOnlyList<string> OutputProfileIds =
        ["video.landscape.v1", "video.vertical.v1", "video.square.v1"];
}

/// <summary>严格解析并校验 C008A2 响应；重算 plan digest 与 Core 的规范 JSON 逐字一致。</summary>
public static class CaptionOverlayPlanParser
{
    private static readonly JsonSerializerOptions Strict = new()
    {
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        PropertyNameCaseInsensitive = false,
    };

    public static CaptionOverlayPlanResponseRecord Parse(ReadOnlySpan<byte> json)
    {
        JsonNode? root;
        CaptionOverlayPlanResponseRecord? response;
        try
        {
            root = JsonNode.Parse(json);
            response = root?.Deserialize<CaptionOverlayPlanResponseRecord>(Strict);
        }
        catch (JsonException exception)
        {
            throw new TextOverlayException(TextOverlayException.PlanInvalid, exception);
        }
        catch (InvalidOperationException exception)
        {
            throw new TextOverlayException(TextOverlayException.PlanInvalid, exception);
        }
        if (response is null || root?["plan"] is not JsonNode planNode)
        {
            throw new TextOverlayException(TextOverlayException.PlanInvalid);
        }

        Validate(response);
        var recomputed = Convert.ToHexString(SHA256.HashData(CanonicalJson.Serialize(planNode)))
            .ToLowerInvariant();
        if (!string.Equals(recomputed, response.CaptionOverlayPlanDigest, StringComparison.Ordinal))
        {
            throw new TextOverlayException(TextOverlayException.PlanInvalid);
        }
        return response;
    }

    /// <summary>形状校验：任何违反都是 TEXT_OVERLAY_PLAN_INVALID，且从不回显文案。</summary>
    public static void Validate(CaptionOverlayPlanResponseRecord response)
    {
        var plan = response?.Plan;
        if (plan is null
            || response is null
            || plan.SchemaVersion != "1.0"
            || string.IsNullOrWhiteSpace(plan.ProductionJobId) || plan.ProductionJobId.Length > 120
            || !IsSha(response.CaptionOverlayPlanDigest)
            || !IsSha(plan.CreativePackageDigest)
            || !IsSha(plan.ProductionPlanDigest)
            || plan.TargetRuntimeMs is <= 0 or > 600_000
            || !CaptionOverlayConstants.OutputProfileIds.Contains(plan.OutputProfileId)
            || plan.OverlayStyleProfileId != CaptionOverlayConstants.OverlayStyleProfileId
            || plan.CaptionStyleProfileId != CaptionOverlayConstants.CaptionStyleProfileId
            || plan.FontProfileId != CaptionOverlayConstants.FontProfileId
            || plan.Captions is null || plan.Overlays is null
            // v1 renders authored overlays only; captions are reserved and must never be silently dropped.
            || plan.CaptionsRequired || plan.Captions.Count != 0
            || plan.OverlaysRequired != (plan.Overlays.Count > 0)
            || plan.Overlays.Count > 60)
        {
            throw new TextOverlayException(TextOverlayException.PlanInvalid);
        }

        var previousStart = -1;
        for (var index = 0; index < plan.Overlays.Count; index++)
        {
            var cue = plan.Overlays[index];
            if (cue is null
                || cue.CueKind != "overlay"
                || cue.Order != index + 1
                || !IsSafeId(cue.CueId) || !IsSafeId(cue.BeatId)
                || string.IsNullOrEmpty(cue.Text) || cue.Text.Length > 800
                || cue.Text != cue.Text.Trim()
                || !IsSha(cue.TextSha256)
                || !string.Equals(
                    Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(cue.Text))).ToLowerInvariant(),
                    cue.TextSha256,
                    StringComparison.Ordinal)
                || cue.StartMs < 0 || cue.EndMs <= cue.StartMs
                || cue.EndMs > plan.TargetRuntimeMs
                || cue.StartMs < previousStart)
            {
                throw new TextOverlayException(TextOverlayException.PlanInvalid);
            }
            previousStart = cue.StartMs;
        }
    }

    private static bool IsSha(string? value) =>
        value is { Length: 64 } && value.All(static ch => ch is (>= '0' and <= '9') or (>= 'a' and <= 'f'));

    private static bool IsSafeId(string? value) =>
        value is { Length: >= 1 and <= 80 }
        && value.All(static ch => char.IsAsciiLetterOrDigit(ch) || ch is '_' or '.' or '-');
}

/// <summary>与 Python json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False) 逐字一致的规范 JSON。</summary>
public static class CanonicalJson
{
    private const string Quote = "\"";
    private const string Backslash = "\\";

    public static byte[] Serialize(JsonNode node)
    {
        var builder = new StringBuilder();
        Append(builder, node);
        return Encoding.UTF8.GetBytes(builder.ToString());
    }

    private static void Append(StringBuilder builder, JsonNode? node)
    {
        switch (node)
        {
            case null:
                builder.Append("null");
                break;
            case JsonObject obj:
                builder.Append("{");
                var first = true;
                foreach (var pair in obj.OrderBy(static item => item.Key, StringComparer.Ordinal))
                {
                    if (!first)
                    {
                        builder.Append(",");
                    }
                    first = false;
                    AppendString(builder, pair.Key);
                    builder.Append(":");
                    Append(builder, pair.Value);
                }
                builder.Append("}");
                break;
            case JsonArray array:
                builder.Append("[");
                for (var index = 0; index < array.Count; index++)
                {
                    if (index > 0)
                    {
                        builder.Append(",");
                    }
                    Append(builder, array[index]);
                }
                builder.Append("]");
                break;
            case JsonValue value:
                if (value.TryGetValue<string>(out var text))
                {
                    AppendString(builder, text);
                }
                else if (value.TryGetValue<bool>(out var flag))
                {
                    builder.Append(flag ? "true" : "false");
                }
                else
                {
                    builder.Append(value.ToJsonString());
                }
                break;
        }
    }

    private static void AppendString(StringBuilder builder, string value)
    {
        builder.Append(Quote);
        foreach (var ch in value)
        {
            var code = (int)ch;
            if (code == 0x22)
            {
                builder.Append(Backslash).Append(Quote);
            }
            else if (code == 0x5C)
            {
                builder.Append(Backslash).Append(Backslash);
            }
            else if (code == 0x0A)
            {
                builder.Append(Backslash).Append("n");
            }
            else if (code == 0x0D)
            {
                builder.Append(Backslash).Append("r");
            }
            else if (code == 0x09)
            {
                builder.Append(Backslash).Append("t");
            }
            else if (code == 0x08)
            {
                builder.Append(Backslash).Append("b");
            }
            else if (code == 0x0C)
            {
                builder.Append(Backslash).Append("f");
            }
            else if (code < 0x20)
            {
                builder.Append(Backslash).Append("u").Append(code.ToString("x4", System.Globalization.CultureInfo.InvariantCulture));
            }
            else
            {
                builder.Append(ch);
            }
        }
        builder.Append(Quote);
    }
}
