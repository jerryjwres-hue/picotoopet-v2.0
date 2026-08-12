using System.Net;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 2.3.22.1 Deep-AI 用户侧 REST 路径与无执行配置 payload。</summary>
internal static class DeepAiClientSmokeTests
{
    private static readonly string[] ForbiddenCreateFields =
    [
        "provider_profile_id",
        "provider",
        "model",
        "model_id",
        "endpoint",
        "url",
        "api_key",
        "provider_key",
        "prompt",
        "temperature",
        "tools",
        "command",
        "shell",
        "path",
        "workflow",
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

        var created = await client.PrepareAsync(
            new DeepAiEscalationPrepareRequest(
                "business.local_intelligence",
                "00000000-0000-4000-8000-000000000031")).ConfigureAwait(false);
        SmokeAssert.True(created.Status == "WaitingApproval", "Deep-AI prepare 状态解析错误。");
        SmokeAssert.True(created.MaxCalls == 2, "Deep-AI max_calls 必须冻结为最多 2。");

        var listed = await client.GetEscalationsAsync().ConfigureAwait(false);
        SmokeAssert.True(listed.Length == 1, "Deep-AI list 数量错误。");
        _ = await client.GetEscalationAsync(created.EscalationJobId).ConfigureAwait(false);
        _ = await client.ReconcileAsync(created.EscalationJobId).ConfigureAwait(false);
        var readiness = await client.GetReadinessAsync(created.EscalationJobId).ConfigureAwait(false);
        SmokeAssert.True(!readiness.ExecutionEnabled, "默认 Windows 视图必须看到 paid execution disabled。");
        var usage = await client.GetUsageAsync(created.EscalationJobId).ConfigureAwait(false);
        SmokeAssert.True(usage.CallsUsed == 0 && usage.CostUsd == 0m, "默认 smoke 不得产生付费 usage。");
        var feedback = await client.RecordFeedbackAsync(
            created.EscalationJobId,
            new DeepAiFeedbackRequest(
                "Accepted",
                ["useful", "grounded"],
                new string('f', 64),
                "result-package-001",
                $"feedback:{created.EscalationJobId}:accepted:v1")).ConfigureAwait(false);
        SmokeAssert.True(feedback.HumanAction == "Accepted", "Deep-AI feedback 解析错误。");
        var learning = await client.GetLearningAsync("pet-dryer-us").ConfigureAwait(false);
        SmokeAssert.True(learning.Length == 1, "Deep-AI learning list 数量错误。");

        SmokeAssert.True(
            handler.Paths.SequenceEqual(
            [
                "POST /api/v1/deep-ai/escalations",
                "GET /api/v1/deep-ai/escalations?limit=200",
                $"GET /api/v1/deep-ai/escalations/{created.EscalationJobId}",
                $"POST /api/v1/deep-ai/escalations/{created.EscalationJobId}/reconcile",
                $"GET /api/v1/deep-ai/escalations/{created.EscalationJobId}/readiness",
                $"GET /api/v1/deep-ai/escalations/{created.EscalationJobId}/usage",
                $"POST /api/v1/deep-ai/escalations/{created.EscalationJobId}/feedback",
                "GET /api/v1/deep-ai/learning?project_key=pet-dryer-us&limit=200",
            ]),
            "Deep-AI client 访问了未批准 REST 路径。");
        var createBody = handler.CreateBody ?? throw new InvalidOperationException("Deep-AI create body 缺失。");
        SmokeAssert.True(createBody.Contains("\"source_kind\"", StringComparison.Ordinal), "create body 缺 source_kind。");
        SmokeAssert.True(createBody.Contains("\"source_id\"", StringComparison.Ordinal), "create body 缺 source_id。");
        foreach (var forbidden in ForbiddenCreateFields)
        {
            SmokeAssert.True(
                !createBody.Contains($"\"{forbidden}\"", StringComparison.Ordinal),
                $"Deep-AI create body 泄露禁止字段：{forbidden}");
        }
    }

    private sealed class FakeHandler : HttpMessageHandler
    {
        private const string JobId = "00000000-0000-4000-8000-000000000032";
        public List<string> Paths { get; } = [];
        public string? CreateBody { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var pathAndQuery = request.RequestUri?.PathAndQuery ?? string.Empty;
            Paths.Add($"{request.Method.Method} {pathAndQuery}");
            if (request.Method == HttpMethod.Post && pathAndQuery == "/api/v1/deep-ai/escalations")
            {
                CreateBody = await request.Content!.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
                return Json(Job());
            }
            if (request.Method == HttpMethod.Get && pathAndQuery == "/api/v1/deep-ai/escalations?limit=200")
            {
                return Json($"[{Job()}]");
            }
            if (request.Method == HttpMethod.Get && pathAndQuery == $"/api/v1/deep-ai/escalations/{JobId}")
            {
                return Json(Job());
            }
            if (request.Method == HttpMethod.Post && pathAndQuery == $"/api/v1/deep-ai/escalations/{JobId}/reconcile")
            {
                return Json(Job());
            }
            if (request.Method == HttpMethod.Get && pathAndQuery == $"/api/v1/deep-ai/escalations/{JobId}/readiness")
            {
                return Json($$"""
                {"escalation_job_id":"{{JobId}}","execution_enabled":false,"provider_ready":false,"reason_code":"DEEP_AI_EXECUTION_DISABLED","manual_handoff_id":"handoff-001"}
                """);
            }
            if (request.Method == HttpMethod.Get && pathAndQuery == $"/api/v1/deep-ai/escalations/{JobId}/usage")
            {
                return Json($$"""
                {"escalation_job_id":"{{JobId}}","calls_used":0,"input_tokens":0,"output_tokens":0,"cost_usd":0}
                """);
            }
            if (request.Method == HttpMethod.Post && pathAndQuery == $"/api/v1/deep-ai/escalations/{JobId}/feedback")
            {
                return Json($$"""
                {"event_id":"event-001","idempotency_key":"feedback:{{JobId}}:accepted:v1","project_key":"pet-dryer-us","source_kind":"business.local_intelligence","source_id":"00000000-0000-4000-8000-000000000031","escalation_job_id":"{{JobId}}","local_profile":null,"local_model_id":null,"local_template_version":null,"local_attempt_count":null,"local_quality_outcome":"NEEDS_DEEP_AI","quality_reasons":[],"provider_profile_id":"paid.reasoning.v1","provider_model_id":"gpt-5.6-terra","sanitized_input_digest":"{{new string('a', 64)}}","paid_output_digest":null,"input_tokens":null,"output_tokens":null,"cost_usd":null,"paid_validation_outcome":null,"human_action":"Accepted","reason_tags":["useful","grounded"],"final_content_digest":"{{new string('f', 64)}}","downstream_ref":"result-package-001"}
                """);
            }
            if (request.Method == HttpMethod.Get && pathAndQuery == "/api/v1/deep-ai/learning?project_key=pet-dryer-us&limit=200")
            {
                return Json($$"""
                [{"event_id":"event-001","idempotency_key":"feedback:{{JobId}}:accepted:v1","project_key":"pet-dryer-us","source_kind":"business.local_intelligence","source_id":"00000000-0000-4000-8000-000000000031","local_quality_outcome":"NEEDS_DEEP_AI","escalation_job_id":"{{JobId}}","human_action":"Accepted","reason_tags":["useful"],"final_content_digest":"{{new string('f', 64)}}","created_at":"2026-08-11T23:00:00Z"}]
                """);
            }
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        }

        private static string Job() => $$"""
        {
          "escalation_job_id":"{{JobId}}",
          "source_kind":"business.local_intelligence",
          "source_id":"00000000-0000-4000-8000-000000000031",
          "source_digest":"{{new string('b', 64)}}",
          "policy_version":"deep-ai.escalation.v1",
          "sanitized_package_relpath":"deep-ai/requests/request.json",
          "sanitized_package_digest":"{{new string('a', 64)}}",
          "sanitizer_version":"deep-ai.sanitizer.v1",
          "provider_profile_id":"paid.reasoning.v1",
          "provider_profile_digest":"{{new string('c', 64)}}",
          "model_id":"gpt-5.6-terra",
          "max_input_tokens":12000,
          "max_output_tokens":4000,
          "max_calls":2,
          "max_cost_usd":0.50,
          "status":"WaitingApproval",
          "approval_id":"approval-001",
          "approval_digest":"{{new string('d', 64)}}",
          "approval_expires_at":"2026-08-12T00:00:00Z",
          "validation_outcome":null,
          "accepted_result_digest":null,
          "accepted_result_relpath":null,
          "failure_code":null,
          "error_message":null,
          "created_at":"2026-08-11T23:00:00Z",
          "updated_at":"2026-08-11T23:00:00Z",
          "finished_at":null
        }
        """;

        private static HttpResponseMessage Json(string content) =>
            new(HttpStatusCode.OK)
            {
                Content = new StringContent(content, Encoding.UTF8, "application/json"),
            };
    }
}
