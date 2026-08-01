using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>可重放 WebSocket 事件信封。</summary>
public sealed record EventEnvelope(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("sequence")] long Sequence,
    [property: JsonPropertyName("event_id")] string EventId,
    [property: JsonPropertyName("topic")] string Topic,
    [property: JsonPropertyName("trace_id")] string? TraceId,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("payload")] JsonElement Payload)
{
    /// <summary>尝试把任务事件负载反序列化为任务快照。</summary>
    public bool TryGetTask(JsonSerializerOptions options, out TaskRecord? task)
    {
        task = null;
        if (!string.Equals(Topic, "task.updated", StringComparison.Ordinal))
        {
            return false;
        }

        task = Payload.Deserialize<TaskRecord>(options);
        return task is not null;
    }
}

/// <summary>REST 请求完成后的性能样本。</summary>
public sealed record RequestMeasurement(
    string Operation,
    double DurationMilliseconds,
    string TraceId,
    int StatusCode);

/// <summary>WebSocket Ping/Pong 往返样本。</summary>
public sealed record SocketMeasurement(
    double DurationMilliseconds,
    string Nonce);
