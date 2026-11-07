using System.IO;
using System.Net.Http;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace PicotooPet.OwnerReview.SmokeTests;

/// <summary>一次被记录的合成请求（只记录，不触网）。</summary>
internal sealed record RecordedRequest(string Method, string Path, string? Authorization, string? IdempotencyKey, string Body);

/// <summary>合成的 Mock Core：只依据冻结 OpenAPI 的形状回答，完全不触网。</summary>
internal sealed class MockOwnerReviewCore : HttpMessageHandler
{
    public const string Goal = "goal-synthetic-0001";
    public const string Digest = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    public static readonly Uri Base = new("https://owner-review-mock.invalid/");

    private readonly List<RecordedRequest> _requests = [];

    public IReadOnlyList<RecordedRequest> Requests => _requests;

    /// <summary>可覆盖的响应：(状态码, 响应体)。返回 null 表示使用默认合成响应。</summary>
    public Func<RecordedRequest, (int Status, string Body)?>? Override { get; set; }

    public int CountPath(string suffix) => _requests.Count(r => r.Path.EndsWith(suffix, StringComparison.Ordinal));

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var body = request.Content is null ? string.Empty : await request.Content.ReadAsStringAsync(cancellationToken);
        var recorded = new RecordedRequest(
            request.Method.Method,
            request.RequestUri!.AbsolutePath,
            request.Headers.Authorization?.ToString(),
            request.Headers.TryGetValues("Idempotency-Key", out var values) ? values.Single() : null,
            body);
        _requests.Add(recorded);
        var (status, payload) = Override?.Invoke(recorded) ?? Default(recorded);
        return new HttpResponseMessage((HttpStatusCode)status)
        {
            Content = new StringContent(payload, Encoding.UTF8, "application/json"),
        };
    }

    public static string Error(string code) =>
        $"{{\"error\":{{\"code\":\"{code}\",\"message\":\"synthetic\",\"retryable\":false,\"trace_id\":\"t\"}}}}";

    private static (int, string) Default(RecordedRequest request)
    {
        if (request.Method == "GET" && request.Path.EndsWith("/proposal", StringComparison.Ordinal))
        {
            return (200, Proposal().ToJsonString());
        }
        if (request.Path.EndsWith("/preview", StringComparison.Ordinal))
        {
            var decisions = JsonNode.Parse(request.Body)!["decisions"]!.AsArray();
            var unknown = decisions.Any(d => d!["decision"]!.GetValue<string>() == "UNKNOWN");
            return (200, Preview(unknown).ToJsonString());
        }
        if (request.Path.EndsWith("/commit", StringComparison.Ordinal))
        {
            return (201, Commit().ToJsonString());
        }
        return (404, Error("NOT_FOUND"));
    }

    /// <summary>合成提案：1 条身份事实、1 条场景事实、1 条冲突事实、1 条创作意图。绝无真实主人数据。</summary>
    public static JsonObject Proposal() => new()
    {
        ["schema_version"] = "owner_structured_review.proposal.v1",
        ["goal_id"] = Goal,
        ["creative_job_id"] = "job-synthetic",
        ["review_actor_id"] = "owner-local",
        ["registry_revision"] = 1,
        ["subject_key"] = "pet:synthetic",
        ["creative_profile"] = "creative.content_plan.v2",
        ["source_set_digest"] = new string('1', 64),
        ["objective_digest"] = new string('2', 64),
        ["source_revision_digest"] = new string('3', 64),
        ["proposal_digest"] = Digest,
        ["source_evidence"] = new JsonArray
        {
            Evidence("evidence-synthetic-identity", "owner_attestation", "D"),
            Evidence("evidence-synthetic-intent", "owner_creative_intent", "E"),
        },
        ["fields"] = new JsonObject
        {
            ["subject_lock.species"] = Field("subject_lock.species", "EXPLICIT", "OWNER_ATTESTATION", "evidence-synthetic-identity", "dog"),
            ["subject_lock.distinguishing_marks"] = Field("subject_lock.distinguishing_marks", "EXPLICIT", "OWNER_ATTESTATION", "evidence-synthetic-identity", new JsonArray("mark-one", "mark-two")),
            ["pose_lock.head_direction"] = Field("pose_lock.head_direction", "UNKNOWN", null, null, null),
            ["scene_lock.lighting"] = Field("scene_lock.lighting", "CONFLICT", "OWNER_ATTESTATION", "evidence-synthetic-identity", "warm"),
            ["allowed_events"] = Field("allowed_events", "EXPLICIT", "OWNER_CREATIVE_INTENT", "evidence-synthetic-intent", new JsonArray("BLINK_AND_REOPEN", "SUBTLE_BREATHING")),
        },
    };

    private static JsonObject Evidence(string id, string type, string trust) => new()
    {
        ["evidence_id"] = id,
        ["evidence_type"] = type,
        ["source"] = "owner_attestation",
        ["trust_level"] = trust,
        ["raw_hash"] = new string('4', 64),
        ["photo_bytes_verified"] = false,
        ["authority_kind"] = "OWNER_ATTESTATION",
    };

    private static JsonObject Field(string path, string status, string? authority, string? evidenceId, JsonNode? value) => new()
    {
        ["field_path"] = path,
        ["status"] = status,
        ["authority_kind"] = authority,
        ["evidence_id"] = evidenceId,
        ["value"] = value,
        ["value_digest"] = value is null ? null : new string('5', 64),
    };

    public static JsonObject Preview(bool needsHuman) => new()
    {
        ["schema_version"] = "owner_structured_review.preview.v1",
        ["goal_id"] = Goal,
        ["subject_key"] = "pet:synthetic",
        ["review_actor_id"] = "owner-local",
        ["proposal_digest"] = Digest,
        ["source_revision_digest"] = new string('3', 64),
        ["review_digest"] = new string('6', 64),
        ["preview_digest"] = new string('7', 64),
        ["outcome"] = needsHuman ? "NEEDS_HUMAN" : "READY",
        ["reason_codes"] = needsHuman ? new JsonArray("OWNER_REVIEW_FIELD_UNKNOWN") : new JsonArray(),
        ["state_facts"] = needsHuman ? null : new JsonObject { ["schema_version"] = "state_facts.v1", ["facts_digest"] = new string('8', 64) },
        ["model_calls"] = 0,
    };

    public static JsonObject Commit() => new()
    {
        ["schema_version"] = "owner_structured_review.commit.v1",
        ["commitment_id"] = "commit-synthetic-1",
        ["goal_id"] = Goal,
        ["subject_key"] = "pet:synthetic",
        ["review_actor_id"] = "owner-local",
        ["source_revision_digest"] = new string('3', 64),
        ["proposal_digest"] = Digest,
        ["review_digest"] = new string('6', 64),
        ["preview_digest"] = new string('7', 64),
        ["facts_id"] = "facts-synthetic",
        ["facts_digest"] = new string('8', 64),
    };

    public static JsonElement ParseElement(string json)
    {
        using var document = JsonDocument.Parse(json);
        return document.RootElement.Clone();
    }
}
