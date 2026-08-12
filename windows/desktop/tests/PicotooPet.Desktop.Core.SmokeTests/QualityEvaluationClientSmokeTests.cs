using System.Net;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 2.3.23.1 质量评估 REST 路径与只读策略边界。</summary>
internal static class QualityEvaluationClientSmokeTests
{
    private static readonly string[] ForbiddenSnapshotFields =
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
    ];

    public static async Task RunAsync()
    {
        var handler = new FakeHandler();
        using var http = new HttpClient(handler)
        {
            BaseAddress = new Uri("http://127.0.0.1:8765/"),
        };
        await using var client = new MacCoreDeepAiClient(
            http,
            "0123456789abcdef0123456789abcdef");

        var snapshot = await client.CreateEvaluationSnapshotAsync(
            new QualityEvaluationSnapshotCreateRequest(
                "pet-dryer-us",
                "quality.offline.v1",
                null,
                null,
                null,
                10000)).ConfigureAwait(false);
        SmokeAssert.True(snapshot.MemberCount == 10, "质量评估 snapshot member_count 解析错误。");

        var run = await client.CreateEvaluationAsync(
            new QualityEvaluationRunCreateRequest(snapshot.SnapshotId)).ConfigureAwait(false);
        SmokeAssert.True(run.Status == "Completed", "质量评估 run 状态解析错误。");

        var metrics = await client.GetEvaluationMetricsAsync(run.EvaluationRunId).ConfigureAwait(false);
        var ratio = metrics.Single(item => item.MetricName == "human_rejected_or_modified_rate");
        SmokeAssert.True(ratio.Numerator == 2 && ratio.Denominator == 5, "质量评估比率必须携带显式分子/分母。");

        var candidates = await client.GetImprovementCandidatesAsync(run.EvaluationRunId).ConfigureAwait(false);
        SmokeAssert.True(candidates.Length == 1, "质量改进候选数量错误。");
        var review = await client.ReviewImprovementCandidateAsync(
            candidates[0].CandidateId,
            new QualityImprovementCandidateReviewRequest(
                "AcceptedForShadow",
                $"review:{candidates[0].CandidateId}:shadow:v1")).ConfigureAwait(false);
        SmokeAssert.True(review.Action == "AcceptedForShadow", "候选 review action 解析错误。");

        SmokeAssert.True(
            handler.Paths.SequenceEqual(
            [
                "POST /api/v1/deep-ai/evaluation-snapshots",
                "POST /api/v1/deep-ai/evaluations",
                $"GET /api/v1/deep-ai/evaluations/{run.EvaluationRunId}/metrics",
                $"GET /api/v1/deep-ai/improvement-candidates?evaluation_run_id={run.EvaluationRunId}",
                $"POST /api/v1/deep-ai/improvement-candidates/{candidates[0].CandidateId}/review",
            ]),
            "质量评估 client 访问了未冻结的 REST 路径。");

        var snapshotBody = handler.SnapshotBody
            ?? throw new InvalidOperationException("质量评估 snapshot body 缺失。");
        SmokeAssert.True(snapshotBody.Contains("\"project_key\"", StringComparison.Ordinal), "snapshot 缺 project_key。");
        SmokeAssert.True(snapshotBody.Contains("\"evaluation_profile_id\"", StringComparison.Ordinal), "snapshot 缺 profile。");
        foreach (var forbidden in ForbiddenSnapshotFields)
        {
            // Payload gate             Windows 不得把执行配置、策略或任意公式送入 Core。
            SmokeAssert.True(
                !snapshotBody.Contains($"\"{forbidden}\"", StringComparison.Ordinal),
                $"质量评估 snapshot body 泄露禁止字段：{forbidden}");
        }
    }

    private sealed class FakeHandler : HttpMessageHandler
    {
        private const string SnapshotId = "00000000-0000-4000-8000-000000000041";
        private const string RunId = "00000000-0000-4000-8000-000000000042";
        private const string CandidateId = "00000000-0000-4000-8000-000000000043";

        public List<string> Paths { get; } = [];
        public string? SnapshotBody { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var pathAndQuery = request.RequestUri?.PathAndQuery ?? string.Empty;
            Paths.Add($"{request.Method.Method} {pathAndQuery}");
            if (request.Method == HttpMethod.Post && pathAndQuery == "/api/v1/deep-ai/evaluation-snapshots")
            {
                SnapshotBody = await request.Content!.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
                return Json($$"""
                {"snapshot_id":"{{SnapshotId}}","project_key":"pet-dryer-us","evaluation_profile_id":"quality.offline.v1","stage_profile":null,"start_at":null,"end_at":null,"limit_count":10000,"scope_digest":"{{new string('a', 64)}}","snapshot_digest":"{{new string('b', 64)}}","member_count":10,"created_at":"2026-08-12T16:00:00Z"}
                """);
            }
            if (request.Method == HttpMethod.Post && pathAndQuery == "/api/v1/deep-ai/evaluations")
            {
                return Json($$"""
                {"evaluation_run_id":"{{RunId}}","snapshot_id":"{{SnapshotId}}","evaluation_profile_id":"quality.offline.v1","rule_version":"quality.offline.v1","status":"Completed","report_digest":"{{new string('c', 64)}}","created_at":"2026-08-12T16:01:00Z","completed_at":"2026-08-12T16:01:00Z"}
                """);
            }
            if (request.Method == HttpMethod.Get && pathAndQuery == $"/api/v1/deep-ai/evaluations/{RunId}/metrics")
            {
                return Json($$"""
                [{"metric_id":"metric-001","evaluation_run_id":"{{RunId}}","metric_name":"human_rejected_or_modified_rate","value":0.4,"numerator":2,"denominator":5,"availability":"available","cohort_dimension":null,"cohort_key":null,"cohort_digest":"{{new string('d', 64)}}"}]
                """);
            }
            if (request.Method == HttpMethod.Get && pathAndQuery == $"/api/v1/deep-ai/improvement-candidates?evaluation_run_id={RunId}")
            {
                return Json($$"""
                [{"candidate_id":"{{CandidateId}}","project_key":"pet-dryer-us","evaluation_run_id":"{{RunId}}","snapshot_id":"{{SnapshotId}}","rule_version":"quality.offline.v1","candidate_class":"PROMPT_REVIEW","cohort_dimension":"stage_profile","cohort_key":"reviews.voice_of_customer.v1","cohort_digest":"{{new string('e', 64)}}","reason_codes":["HUMAN_REJECTED_OR_MODIFIED_RATE_HIGH"],"status":"Prepared","candidate_digest":"{{new string('f', 64)}}","created_at":"2026-08-12T16:01:00Z","updated_at":"2026-08-12T16:01:00Z"}]
                """);
            }
            if (request.Method == HttpMethod.Post && pathAndQuery == $"/api/v1/deep-ai/improvement-candidates/{CandidateId}/review")
            {
                return Json($$"""
                {"review_id":"review-001","candidate_id":"{{CandidateId}}","action":"AcceptedForShadow","idempotency_key":"review:{{CandidateId}}:shadow:v1","created_at":"2026-08-12T16:02:00Z"}
                """);
            }
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        }

        private static HttpResponseMessage Json(string content) =>
            new(HttpStatusCode.OK)
            {
                Content = new StringContent(content, Encoding.UTF8, "application/json"),
            };
    }
}
