using System.Net;
using System.Text;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 Phase 10A 使用固定类型、幂等键和有界响应，不暴露任意路径或命令。</summary>
internal static class HandoffPreparationSmokeTests
{
    public static async Task RunAsync()
    {
        var handler = new HandoffFixtureHandler();
        using var httpClient = new HttpClient(handler);
        await using var client = new MacCoreHandoffClient(
            httpClient,
            new Uri("http://127.0.0.1:18186/", UriKind.Absolute),
            "fixture-token");

        var templates = await client.GetTemplatesAsync(CancellationToken.None)
            .ConfigureAwait(false);
        SmokeAssert.Equal(1, templates.Length, "Handoff 模板数量错误");
        SmokeAssert.Equal(
            "picotoopet-repo-maintenance-v1",
            templates[0].TemplateId,
            "Handoff 模板 ID 错误");
        SmokeAssert.True(
            !templates[0].ProviderConfigured,
            "Phase 10A 不得伪造 Provider 已配置");

        var prepared = await client.PrepareAsync(
            new HandoffPrepareRequest(
                "picotoopet-repo-maintenance-v1",
                "准备安全修复",
                "只生成受控摘要并提交审批。",
                1800),
            "windows-handoff-prepare-001",
            CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal("prepared", prepared.Status, "Handoff 准备状态错误");
        SmokeAssert.Equal(64, prepared.RequestDigest.Length, "request digest 长度错误");
        SmokeAssert.Equal(64, prepared.PackageDigest.Length, "package digest 长度错误");

        var submitted = await client.SubmitApprovalAsync(
            prepared.HandoffId,
            "windows-handoff-submit-001",
            CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal(
            "waiting_approval",
            submitted.Status,
            "Handoff 提交审批状态错误");
        SmokeAssert.True(
            !string.IsNullOrWhiteSpace(submitted.ApprovalId),
            "Handoff 提交审批后缺少 approval_id");

        SmokeAssert.True(
            handler.Requests.All(item => item.Authorization == "Bearer fixture-token"),
            "Handoff 请求没有使用设备 Bearer Token");
        SmokeAssert.True(
            handler.Requests.Where(item => item.Method == "POST")
                .All(item => !string.IsNullOrWhiteSpace(item.IdempotencyKey)),
            "Handoff 写操作缺少 Idempotency-Key");
        SmokeAssert.True(
            handler.Requests.All(item => !item.Body.Contains("allowed_write", StringComparison.OrdinalIgnoreCase)),
            "Windows 不得发送任意写入路径");
        SmokeAssert.True(
            handler.Requests.All(item => !item.Body.Contains("command", StringComparison.OrdinalIgnoreCase)),
            "Windows 不得发送任意命令");
    }

    private sealed class HandoffFixtureHandler : HttpMessageHandler
    {
        public List<CapturedRequest> Requests { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var body = request.Content is null
                ? string.Empty
                : await request.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            Requests.Add(new CapturedRequest(
                request.Method.Method,
                request.RequestUri?.AbsolutePath ?? string.Empty,
                request.Headers.Authorization?.ToString() ?? string.Empty,
                request.Headers.TryGetValues("Idempotency-Key", out var values)
                    ? values.Single()
                    : null,
                body));

            var path = request.RequestUri?.AbsolutePath ?? string.Empty;
            var json = path switch
            {
                "/api/v1/handoffs/templates" => TemplatesJson,
                "/api/v1/handoffs/prepare" => PreparedJson,
                _ when path.EndsWith("/submit-approval", StringComparison.Ordinal) => SubmittedJson,
                _ => throw new InvalidOperationException($"未预期的 Handoff 路径：{path}"),
            };
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(json, Encoding.UTF8, "application/json"),
            };
        }
    }

    private sealed record CapturedRequest(
        string Method,
        string Path,
        string Authorization,
        string? IdempotencyKey,
        string Body);

    private const string TemplatesJson = """
        [{
          "template_id":"picotoopet-repo-maintenance-v1",
          "display_name":"PicotooPet 仓库维护",
          "provider":"manual",
          "provider_configured":false,
          "repo_url":"https://github.com/jerryjwres-hue/picotoopet-v2.0",
          "base_ref":"feature/phase23-slice-d-diagnostic-snapshot-release",
          "base_commit":"5db6b1f9340ff5abe0d38bbb7b6e3ee9b48c34bb"
        }]
        """;

    private const string PreparedJson = """
        {
          "handoff_id":"handoff-001",
          "template_id":"picotoopet-repo-maintenance-v1",
          "template_name":"PicotooPet 仓库维护",
          "title":"准备安全修复",
          "objective_summary":"只生成受控摘要并提交审批。",
          "status":"prepared",
          "provider":"manual",
          "provider_configured":false,
          "repo_url":"https://github.com/jerryjwres-hue/picotoopet-v2.0",
          "base_ref":"feature/phase23-slice-d-diagnostic-snapshot-release",
          "base_commit":"5db6b1f9340ff5abe0d38bbb7b6e3ee9b48c34bb",
          "sensitivity":"internal",
          "planned_read_count":1,
          "planned_write_count":1,
          "required_tests":["python-regression","windows-wpf-behavior","windows-formal-release","mac-core-arm64"],
          "budget_summary":"20 turns · 1800 秒 · 1 并发 · 无网络工具",
          "request_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "package_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "approval_id":null,
          "created_at":"2026-08-05T19:30:00Z",
          "updated_at":"2026-08-05T19:30:00Z",
          "expires_at":"2026-08-05T20:00:00Z",
          "security_boundaries":["Provider execution is disabled in Phase 10A."]
        }
        """;

    private const string SubmittedJson = """
        {
          "handoff_id":"handoff-001",
          "template_id":"picotoopet-repo-maintenance-v1",
          "template_name":"PicotooPet 仓库维护",
          "title":"准备安全修复",
          "objective_summary":"只生成受控摘要并提交审批。",
          "status":"waiting_approval",
          "provider":"manual",
          "provider_configured":false,
          "repo_url":"https://github.com/jerryjwres-hue/picotoopet-v2.0",
          "base_ref":"feature/phase23-slice-d-diagnostic-snapshot-release",
          "base_commit":"5db6b1f9340ff5abe0d38bbb7b6e3ee9b48c34bb",
          "sensitivity":"internal",
          "planned_read_count":1,
          "planned_write_count":1,
          "required_tests":["python-regression","windows-wpf-behavior","windows-formal-release","mac-core-arm64"],
          "budget_summary":"20 turns · 1800 秒 · 1 并发 · 无网络工具",
          "request_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "package_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "approval_id":"approval-001",
          "created_at":"2026-08-05T19:30:00Z",
          "updated_at":"2026-08-05T19:31:00Z",
          "expires_at":"2026-08-05T20:00:00Z",
          "security_boundaries":["Provider execution is disabled in Phase 10A."]
        }
        """;
}
