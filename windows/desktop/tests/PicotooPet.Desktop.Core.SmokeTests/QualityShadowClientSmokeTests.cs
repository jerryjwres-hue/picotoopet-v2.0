using System.Net;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 2.3.24.1 Shadow REST 路径与 caller authority 边界。</summary>
internal static class QualityShadowClientSmokeTests
{
    private static readonly string[] ForbiddenCreateFields =
    [
        "prompt",
        "prompt_template",
        "endpoint",
        "url",
        "model",
        "api_key",
        "provider_key",
        "budget",
        "temperature",
        "tools",
        "command",
        "shell",
        "path",
        "workflow",
        "sql",
        "formula",
        "threshold",
        "split",
        "seed",
    ];

    public static async Task RunAsync()
    {
        var handler = new FakeHandler();
        using var http = new HttpClient(handler)
        {
            BaseAddress = new Uri("http://127.0.0.1:8765/"),
        };
        await using var client = new MacCoreQualityShadowClient(
            http,
            "0123456789abcdef0123456789abcdef");

        var run = await client.CreateAsync(
            new QualityShadowRunCreateRequest(FakeHandler.CandidateId)).ConfigureAwait(false);
        SmokeAssert.True(run.ShadowProfileId == "quality.shadow.v1", "Shadow profile 解析错误。");
        SmokeAssert.True(run.SplitVersion == "quality.shadow.split.v1", "Shadow split version 解析错误。");
        SmokeAssert.True(run.Verdict == "Supported", "Shadow verdict 解析错误。");

        var runs = await client.GetRunsAsync(FakeHandler.CandidateId).ConfigureAwait(false);
        SmokeAssert.True(runs.Length == 1 && runs[0].ShadowRunId == run.ShadowRunId, "Shadow list identity 错误。");

        var metrics = await client.GetMetricsAsync(run.ShadowRunId).ConfigureAwait(false);
        SmokeAssert.True(metrics.Length == 2, "Shadow A/B metric 数量错误。");
        SmokeAssert.True(metrics.All(item => item.Denominator == 30), "Shadow metric 必须保留显式 denominator。");

        var reconciled = await client.ReconcileAsync(run.ShadowRunId).ConfigureAwait(false);
        SmokeAssert.True(reconciled.ReportDigest == run.ReportDigest, "Shadow reconcile 改变了 deterministic report identity。");

        var review = await client.ReviewAsync(
            run.ShadowRunId,
            new QualityShadowReviewRequest(
                "AcceptedForPromotionReview",
                $"shadow-review:{run.ShadowRunId}:promotion:v1")).ConfigureAwait(false);
        SmokeAssert.True(review.Action == "AcceptedForPromotionReview", "Shadow review action 解析错误。");

        SmokeAssert.True(
            handler.Paths.SequenceEqual(
            [
                "POST /api/v1/deep-ai/shadow-runs",
                $"GET /api/v1/deep-ai/shadow-runs?candidate_id={FakeHandler.CandidateId}&limit=200",
                $"GET /api/v1/deep-ai/shadow-runs/{run.ShadowRunId}/metrics",
                $"POST /api/v1/deep-ai/shadow-runs/{run.ShadowRunId}/reconcile",
                $"POST /api/v1/deep-ai/shadow-runs/{run.ShadowRunId}/review",
            ]),
            "Shadow client 访问了未冻结的 REST 路径。");

        var createBody = handler.CreateBody
            ?? throw new InvalidOperationException("Shadow create body 缺失。");
        SmokeAssert.True(createBody.Contains("\"candidate_id\"", StringComparison.Ordinal), "Shadow create 缺 candidate_id。");
        foreach (var forbidden in ForbiddenCreateFields)
        {
            // Authority gate           Windows create body 不得携带任意执行/策略/公式字段。
            SmokeAssert.True(
                !createBody.Contains($"\"{forbidden}\"", StringComparison.Ordinal),
                $"Shadow create body 泄露禁止字段：{forbidden}");
        }
    }

    private sealed class FakeHandler : HttpMessageHandler
    {
        public const string CandidateId = "00000000-0000-4000-8000-000000000051";
        private const string ShadowRunId = "00000000-0000-4000-8000-000000000052";

        public List<string> Paths { get; } = [];
        public string? CreateBody { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var pathAndQuery = request.RequestUri?.PathAndQuery ?? string.Empty;
            Paths.Add($"{request.Method.Method} {pathAndQuery}");
            if (request.Method == HttpMethod.Post && pathAndQuery == "/api/v1/deep-ai/shadow-runs")
            {
                CreateBody = await request.Content!.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
                return Json(RunJson());
            }
            if (request.Method == HttpMethod.Get && pathAndQuery == $"/api/v1/deep-ai/shadow-runs?candidate_id={CandidateId}&limit=200")
            {
                return Json($"[{RunJson()}]");
            }
            if (request.Method == HttpMethod.Get && pathAndQuery == $"/api/v1/deep-ai/shadow-runs/{ShadowRunId}/metrics")
            {
                return Json($$"""
                [
                  {"metric_id":"metric-a","shadow_run_id":"{{ShadowRunId}}","arm":"baseline","metric_name":"human_rejected_or_modified_rate","value":1.0,"numerator":30,"denominator":30,"availability":"available","arm_digest":"{{new string('a', 64)}}"},
                  {"metric_id":"metric-b","shadow_run_id":"{{ShadowRunId}}","arm":"shadow","metric_name":"human_rejected_or_modified_rate","value":1.0,"numerator":30,"denominator":30,"availability":"available","arm_digest":"{{new string('b', 64)}}"}
                ]
                """);
            }
            if (request.Method == HttpMethod.Post && pathAndQuery == $"/api/v1/deep-ai/shadow-runs/{ShadowRunId}/reconcile")
            {
                return Json(RunJson());
            }
            if (request.Method == HttpMethod.Post && pathAndQuery == $"/api/v1/deep-ai/shadow-runs/{ShadowRunId}/review")
            {
                return Json($$"""
                {"review_id":"review-shadow-001","shadow_run_id":"{{ShadowRunId}}","action":"AcceptedForPromotionReview","idempotency_key":"shadow-review:{{ShadowRunId}}:promotion:v1","created_at":"2026-08-12T18:40:00Z"}
                """);
            }
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        }

        private static string RunJson() => $$"""
        {"shadow_run_id":"{{ShadowRunId}}","candidate_id":"{{CandidateId}}","evaluation_run_id":"evaluation-001","snapshot_id":"snapshot-001","project_key":"pet-dryer-us","candidate_class":"PROMPT_REVIEW","candidate_digest":"{{new string('c', 64)}}","snapshot_digest":"{{new string('d', 64)}}","evaluation_report_digest":"{{new string('e', 64)}}","shadow_profile_id":"quality.shadow.v1","split_version":"quality.shadow.split.v1","status":"Completed","verdict":"Supported","input_digest":"{{new string('f', 64)}}","report_digest":"{{new string('1', 64)}}","created_at":"2026-08-12T18:39:00Z","completed_at":"2026-08-12T18:39:01Z"}
        """;

        private static HttpResponseMessage Json(string content) =>
            new(HttpStatusCode.OK)
            {
                Content = new StringContent(content, Encoding.UTF8, "application/json"),
            };
    }
}
