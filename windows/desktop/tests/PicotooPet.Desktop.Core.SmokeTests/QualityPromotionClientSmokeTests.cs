using System.Net;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 2.3.25.1 Promotion REST 路径、exact digest 与 caller-authority 边界。</summary>
internal static class QualityPromotionClientSmokeTests
{
    private static readonly string[] ForbiddenCreateFields =
    [
        "prompt", "model", "provider", "endpoint", "api_key", "budget", "temperature",
        "tools", "command", "shell", "path", "workflow", "sql", "formula", "threshold",
        "version_no", "slot_key", "patch",
    ];

    public static async Task RunAsync()
    {
        var handler = new FakeHandler();
        using var http = new HttpClient(handler)
        {
            BaseAddress = new Uri("http://127.0.0.1:8765/"),
        };
        await using var client = new MacCoreQualityPromotionClient(
            http,
            "0123456789abcdef0123456789abcdef");

        var promotion = await client.CreateAsync(
            new QualityPromotionCreateRequest(FakeHandler.ShadowRunId)).ConfigureAwait(false);
        SmokeAssert.True(promotion.PromotionProfileId == "quality.promotion.v1", "Promotion profile 解析错误。");
        SmokeAssert.True(promotion.VersionNo == 1, "Promotion version 解析错误。");
        SmokeAssert.True(promotion.Status == "AwaitingApproval", "Promotion status 解析错误。");

        var approval = await client.GetActivationRequestAsync(promotion.PromotionId).ConfigureAwait(false);
        SmokeAssert.True(approval.ApprovalKind == "PromotionActivation", "Activation kind 解析错误。");
        var activated = await client.DecideActivationAsync(
            promotion.PromotionId,
            new QualityPromotionDecisionRequest(
                "Approved",
                approval.RequestDigest,
                $"promotion-activate:{promotion.PromotionId}:v1")).ConfigureAwait(false);
        SmokeAssert.True(activated.Status == "Active", "Promotion activation 解析错误。");

        var rollback = await client.RequestRollbackAsync(
            promotion.PromotionId,
            new QualityPromotionRollbackRequest("OperatorDecision")).ConfigureAwait(false);
        var rolledBack = await client.DecideRollbackAsync(
            promotion.PromotionId,
            new QualityPromotionDecisionRequest(
                "Approved",
                rollback.RequestDigest,
                $"promotion-rollback:{promotion.PromotionId}:v1")).ConfigureAwait(false);
        SmokeAssert.True(rolledBack.Status == "RolledBack", "Promotion rollback 解析错误。");

        var history = await client.GetHistoryAsync(promotion.PromotionId).ConfigureAwait(false);
        SmokeAssert.True(history.Decisions.Count == 2, "Promotion 决策历史数量错误。");
        SmokeAssert.True(history.Rollbacks.Count == 1, "Promotion rollback 历史数量错误。");

        var createBody = handler.CreateBody
            ?? throw new InvalidOperationException("Promotion create body 缺失。");
        SmokeAssert.True(createBody.Contains("\"shadow_run_id\"", StringComparison.Ordinal), "Promotion create 缺 shadow_run_id。");
        foreach (var forbidden in ForbiddenCreateFields)
        {
            // Authority gate           Windows create body 不得携带任意执行策略或客户端版本槽位。
            SmokeAssert.True(
                !createBody.Contains($"\"{forbidden}\"", StringComparison.Ordinal),
                $"Promotion create body 泄露禁止字段：{forbidden}");
        }

        SmokeAssert.True(
            handler.Paths.SequenceEqual(
            [
                "POST /api/v1/deep-ai/promotions",
                $"GET /api/v1/deep-ai/promotions/{FakeHandler.PromotionId}/activation-request",
                $"POST /api/v1/deep-ai/promotions/{FakeHandler.PromotionId}/activation-decision",
                $"POST /api/v1/deep-ai/promotions/{FakeHandler.PromotionId}/rollback-request",
                $"POST /api/v1/deep-ai/promotions/{FakeHandler.PromotionId}/rollback-decision",
                $"GET /api/v1/deep-ai/promotions/{FakeHandler.PromotionId}/history",
            ]),
            "Promotion client 访问了未冻结的 REST 路径。");
    }

    private sealed class FakeHandler : HttpMessageHandler
    {
        public const string ShadowRunId = "00000000-0000-4000-8000-000000000061";
        public const string PromotionId = "00000000-0000-4000-8000-000000000062";
        private static readonly string RequestDigest = new('a', 64);
        private static readonly string RollbackRequestDigest = new('b', 64);

        public List<string> Paths { get; } = [];
        public string? CreateBody { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var pathAndQuery = request.RequestUri?.PathAndQuery ?? string.Empty;
            Paths.Add($"{request.Method.Method} {pathAndQuery}");
            if (request.Method == HttpMethod.Post && pathAndQuery == "/api/v1/deep-ai/promotions")
            {
                CreateBody = await request.Content!.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
                return Json(PromotionJson("AwaitingApproval"));
            }
            if (request.Method == HttpMethod.Get && pathAndQuery == $"/api/v1/deep-ai/promotions/{PromotionId}/activation-request")
            {
                return Json(ApprovalJson("PromotionActivation", RequestDigest, null));
            }
            if (request.Method == HttpMethod.Post && pathAndQuery == $"/api/v1/deep-ai/promotions/{PromotionId}/activation-decision")
            {
                return Json(PromotionJson("Active"));
            }
            if (request.Method == HttpMethod.Post && pathAndQuery == $"/api/v1/deep-ai/promotions/{PromotionId}/rollback-request")
            {
                return Json(ApprovalJson("PromotionRollback", RollbackRequestDigest, "OperatorDecision"));
            }
            if (request.Method == HttpMethod.Post && pathAndQuery == $"/api/v1/deep-ai/promotions/{PromotionId}/rollback-decision")
            {
                return Json(PromotionJson("RolledBack"));
            }
            if (request.Method == HttpMethod.Get && pathAndQuery == $"/api/v1/deep-ai/promotions/{PromotionId}/history")
            {
                return Json($$"""
                {"decisions":[
                  {"decision_id":"d1","approval_request_id":"r1","promotion_id":"{{PromotionId}}","decision":"Approved","request_digest":"{{RequestDigest}}","idempotency_key":"a1","decision_digest":"{{new string('c',64)}}","created_at":"2026-08-12T22:10:00Z"},
                  {"decision_id":"d2","approval_request_id":"r2","promotion_id":"{{PromotionId}}","decision":"Approved","request_digest":"{{RollbackRequestDigest}}","idempotency_key":"r1","decision_digest":"{{new string('d',64)}}","created_at":"2026-08-12T22:11:00Z"}
                ],"rollbacks":[
                  {"rollback_id":"rb1","promotion_id":"{{PromotionId}}","restore_promotion_id":null,"approval_request_id":"r2","rollback_reason_code":"OperatorDecision","request_digest":"{{RollbackRequestDigest}}","rollback_digest":"{{new string('e',64)}}","created_at":"2026-08-12T22:11:00Z"}
                ]}
                """);
            }
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        }

        private static string PromotionJson(string status) => $$"""
        {"promotion_id":"{{PromotionId}}","shadow_run_id":"{{ShadowRunId}}","candidate_id":"candidate-001","project_key":"pet-dryer-us","candidate_class":"PROMPT_REVIEW","candidate_digest":"{{new string('1',64)}}","shadow_report_digest":"{{new string('2',64)}}","evaluation_report_digest":"{{new string('3',64)}}","snapshot_digest":"{{new string('4',64)}}","promotion_profile_id":"quality.promotion.v1","slot_key":"{{new string('5',64)}}","version_no":1,"proposal_digest":"{{new string('6',64)}}","status":"{{status}}","supersedes_promotion_id":null,"created_at":"2026-08-12T22:09:00Z","activated_at":null,"rolled_back_at":null}
        """;

        private static string ApprovalJson(string kind, string digest, string? reason) => $$"""
        {"approval_request_id":"request-001","promotion_id":"{{PromotionId}}","approval_kind":"{{kind}}","request_digest":"{{digest}}","status":"Pending","rollback_reason_code":{{(reason is null ? "null" : $"\"{reason}\"")}},"restore_promotion_id":null,"created_at":"2026-08-12T22:09:00Z","expires_at":"2026-08-12T22:39:00Z","resolved_at":null}
        """;

        private static HttpResponseMessage Json(string content) =>
            new(HttpStatusCode.OK)
            {
                Content = new StringContent(content, Encoding.UTF8, "application/json"),
            };
    }
}
