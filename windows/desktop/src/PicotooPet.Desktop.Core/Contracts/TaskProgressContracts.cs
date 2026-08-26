using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>Mac Core 耐久进度中的一条不可变活动事实。</summary>
public sealed record TaskProgressEvent(
    [property: JsonPropertyName("task_id")] string TaskId,
    [property: JsonPropertyName("sequence")] long Sequence,
    [property: JsonPropertyName("stage")] string Stage,
    [property: JsonPropertyName("completed")] int? Completed,
    [property: JsonPropertyName("total")] int? Total,
    [property: JsonPropertyName("message")] string Message,
    [property: JsonPropertyName("component")] string Component,
    [property: JsonPropertyName("details")] JsonElement Details,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

/// <summary>Windows 只读投影的 Core 权威进度快照；百分比仅使用服务端明确返回值。</summary>
public sealed record TaskProgressSnapshot(
    [property: JsonPropertyName("task_id")] string TaskId,
    [property: JsonPropertyName("stage")] string? Stage,
    [property: JsonPropertyName("completed")] int? Completed,
    [property: JsonPropertyName("total")] int? Total,
    [property: JsonPropertyName("percent")] double? Percent,
    [property: JsonPropertyName("latest_message")] string? LatestMessage,
    [property: JsonPropertyName("component")] string? Component,
    [property: JsonPropertyName("last_activity_at")] DateTimeOffset? LastActivityAt,
    [property: JsonPropertyName("recent_events")] IReadOnlyList<TaskProgressEvent> RecentEvents);
