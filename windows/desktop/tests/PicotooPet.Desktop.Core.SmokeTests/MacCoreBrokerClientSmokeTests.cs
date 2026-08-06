using System.Net;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 Broker typed client 的固定路径、幂等重试、capability Header 和有界读取。</summary>
internal static class MacCoreBrokerClientSmokeTests
{
    public static async Task RunAsync()
    {
        var handler = new BrokerContractHandler();
        using var httpClient = new HttpClient(handler);
        await using var client = new MacCoreBrokerClient(
            httpClient,
            new Uri("http://127.0.0.1:18186/", UriKind.Absolute),
            "fixture-token");

        var handoffId = "e55edbbb-a71f-4bb3-9d4c-e453654e5579";
        var sessionId = "153704fb-3ce7-4368-ae0e-9520c21ec022";
        var reserved = await client.ReserveMockAsync(
            handoffId,
            "broker-idempotency-001",
            CancellationToken.None).ConfigureAwait(false);

        SmokeAssert.Equal(2, handler.ReserveAttempts, "Broker 预留没有执行单次有界重试");
        SmokeAssert.True(
            handler.ReserveIdempotencyKeys.All(key => key == "broker-idempotency-001"),
            "Broker 预留重试没有复用同一幂等键");
        SmokeAssert.Equal(sessionId, reserved.Record.SessionId, "Broker Session 响应解析错误");
        SmokeAssert.Equal(64, reserved.Capability.Length, "Broker capability 长度错误");
        SmokeAssert.Equal(
            "Bearer fixture-token",
            handler.CapturedAuthorization,
            "Broker typed client 没有使用设备 Bearer 配对合同");

        var envelope = new MockBrokerReturnEnvelope(
            "1.0.0",
            sessionId,
            handoffId,
            "253704fb-3ce7-4368-ae0e-9520c21ec022",
            "local-mock-dev-broker",
            new string('a', 64),
            new string('b', 64),
            new string('c', 64),
            CreateFiles());
        var completed = await client.SubmitReturnAsync(
            sessionId,
            envelope,
            reserved.Capability,
            "broker-return-001",
            CancellationToken.None).ConfigureAwait(false);

        SmokeAssert.Equal("completed", completed.Status, "Broker Return 响应状态错误");
        SmokeAssert.Equal(
            reserved.Capability,
            handler.CapturedCapability,
            "Broker Return 没有使用专用 capability Header");
        SmokeAssert.Equal(
            "broker-return-001",
            handler.CapturedReturnIdempotencyKey,
            "Broker Return 没有发送固定幂等键");
        SmokeAssert.True(handler.ReturnHadJsonContent, "Broker Return 没有发送严格 JSON");
        SmokeAssert.True(
            handler.CapturedReturnBody?.Contains("mock-provider-proof.txt", StringComparison.Ordinal) == true,
            "Broker Return 正文缺少固定证明文件");

        using var oversizedHttp = new HttpClient(new OversizedBrokerHandler());
        await using var oversizedClient = new MacCoreBrokerClient(
            oversizedHttp,
            new Uri("http://127.0.0.1:18186/", UriKind.Absolute),
            "fixture-token");
        try
        {
            await oversizedClient.GetSessionsAsync(CancellationToken.None)
                .ConfigureAwait(false);
            throw new InvalidOperationException("超过 128 KiB 的 Broker 响应未被客户端拒绝。");
        }
        catch (ApiException exception)
        {
            SmokeAssert.Equal(
                "RESPONSE_TOO_LARGE",
                exception.Code,
                "超大 Broker 响应没有返回稳定错误码");
            SmokeAssert.True(!exception.Retryable, "Broker 合同超限不应自动重试");
        }
    }

    private static BrokerReturnFileRecord[] CreateFiles() =>
    [
        new("return_manifest.json", "{}\n"),
        new("session_events.ndjson", "{}\n{}\n{}\n{}\n"),
        new("summary.md", "# Summary\n"),
        new("changed_files.json", "{}\n"),
        new("test_report.json", "{}\n"),
        new("build_report.json", "{}\n"),
        new("security_report.json", "{}\n"),
        new("questions.md", "# Questions\n"),
        new("changes/docs/mock-provider-proof.txt", "proof\n"),
        new("signatures/manifest.sha256", "0  placeholder\n"),
    ];

    private sealed class BrokerContractHandler : HttpMessageHandler
    {
        public int ReserveAttempts { get; private set; }
        public List<string?> ReserveIdempotencyKeys { get; } = [];
        public string? CapturedAuthorization { get; private set; }
        public string? CapturedCapability { get; private set; }
        public string? CapturedReturnIdempotencyKey { get; private set; }
        public bool ReturnHadJsonContent { get; private set; }
        public string? CapturedReturnBody { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            CapturedAuthorization = request.Headers.Authorization?.ToString();
            var path = request.RequestUri?.AbsolutePath ?? string.Empty;
            if (path.EndsWith("/broker-sessions/mock", StringComparison.Ordinal))
            {
                ReserveAttempts++;
                ReserveIdempotencyKeys.Add(ReadHeader(request, "Idempotency-Key"));
                if (ReserveAttempts == 1)
                {
                    return JsonResponse(
                        HttpStatusCode.ServiceUnavailable,
                        """
                        {"error":{"code":"TEMPORARY","message":"temporary","retryable":true,"trace_id":"broker-retry"}}
                        """);
                }
                return JsonResponse(HttpStatusCode.Created, CreateResultJson);
            }

            if (path.EndsWith("/return", StringComparison.Ordinal))
            {
                CapturedCapability = ReadHeader(request, "X-Picotoo-Broker-Session");
                CapturedReturnIdempotencyKey = ReadHeader(request, "Idempotency-Key");
                ReturnHadJsonContent = string.Equals(
                    request.Content?.Headers.ContentType?.MediaType,
                    "application/json",
                    StringComparison.OrdinalIgnoreCase);
                CapturedReturnBody = request.Content is null
                    ? null
                    : await request.Content.ReadAsStringAsync(cancellationToken)
                        .ConfigureAwait(false);
                return JsonResponse(HttpStatusCode.OK, CompletedSessionJson);
            }

            if (request.Method == HttpMethod.Get)
            {
                return JsonResponse(HttpStatusCode.OK, $"[{CompletedSessionJson}]");
            }
            return JsonResponse(HttpStatusCode.OK, CompletedSessionJson);
        }

        private static string? ReadHeader(HttpRequestMessage request, string name) =>
            request.Headers.TryGetValues(name, out var values)
                ? values.Single()
                : null;

        private static HttpResponseMessage JsonResponse(
            HttpStatusCode status,
            string json) =>
            new(status)
            {
                Content = new StringContent(json, Encoding.UTF8, "application/json"),
            };
    }

    private sealed class OversizedBrokerHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new UnknownLengthContent(128 * 1024 + 1),
            });
    }

    private sealed class UnknownLengthContent(int sizeBytes) : HttpContent
    {
        protected override async Task SerializeToStreamAsync(
            Stream stream,
            TransportContext? context)
        {
            var block     = Encoding.UTF8.GetBytes(new string(' ', 4096));
            var remaining = sizeBytes;
            while (remaining > 0)
            {
                var count = Math.Min(block.Length, remaining);
                await stream.WriteAsync(block.AsMemory(0, count)).ConfigureAwait(false);
                remaining -= count;
            }
        }

        protected override bool TryComputeLength(out long length)
        {
            length = 0;
            return false;
        }
    }

    private const string CreateResultJson = """
        {
          "record": {
            "session_id": "153704fb-3ce7-4368-ae0e-9520c21ec022",
            "handoff_id": "e55edbbb-a71f-4bb3-9d4c-e453654e5579",
            "status": "reserved",
            "provider": "local-mock-dev-broker",
            "timeout_seconds": 30,
            "request_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "package_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "return_id": null,
            "event_count": 0,
            "sandbox_digest": null,
            "failure_code": null,
            "created_at": "2026-08-06T00:02:00Z",
            "updated_at": "2026-08-06T00:02:00Z",
            "finished_at": null,
            "execution_notice": "仅运行固定 Mock Provider。"
          },
          "capability": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
        }
        """;

    private const string CompletedSessionJson = """
        {
          "session_id": "153704fb-3ce7-4368-ae0e-9520c21ec022",
          "handoff_id": "e55edbbb-a71f-4bb3-9d4c-e453654e5579",
          "status": "completed",
          "provider": "local-mock-dev-broker",
          "timeout_seconds": 30,
          "request_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "package_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "return_id": "253704fb-3ce7-4368-ae0e-9520c21ec022",
          "event_count": 4,
          "sandbox_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
          "failure_code": null,
          "created_at": "2026-08-06T00:02:00Z",
          "updated_at": "2026-08-06T00:03:00Z",
          "finished_at": "2026-08-06T00:03:00Z",
          "execution_notice": "仅完成固定 Mock Provider 沙盒和 Return 合同验证。"
        }
        """;
}
