using System.Net;
using System.Text;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 Return typed client 的无正文写入、幂等键和有界读取。</summary>
internal static class MacCoreReturnClientSmokeTests
{
    public static async Task RunAsync()
    {
        var handler = new ReturnContractHandler();
        using var httpClient = new HttpClient(handler);
        await using var client = new MacCoreReturnClient(
            httpClient,
            new Uri("http://127.0.0.1:18186/", UriKind.Absolute),
            "fixture-token");

        var listed = await client.GetReturnsAsync(CancellationToken.None)
            .ConfigureAwait(false);
        SmokeAssert.Equal(1, listed.Length, "Return 列表没有按 typed contract 解析");
        SmokeAssert.Equal(
            "contract_validated",
            listed[0].Status,
            "Return 列表状态解析错误");

        var created = await client.RunSelfTestAsync(
            "handoff/approved",
            "return-idempotency-001",
            CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal(
            "return-001",
            created.ReturnId,
            "Return 自测响应解析错误");
        SmokeAssert.Equal(
            HttpMethod.Post,
            handler.CapturedMethod,
            "Return 自测没有使用 POST");
        SmokeAssert.Equal(
            "/api/v1/handoffs/handoff%2Fapproved/returns/self-test",
            handler.CapturedPath,
            "Return 自测路径没有执行单段 URI 转义");
        SmokeAssert.True(
            !handler.HadContent,
            "Return 自测不得发送任意 JSON、文件或命令正文");
        SmokeAssert.Equal(
            "return-idempotency-001",
            handler.CapturedIdempotencyKey,
            "Return 自测没有发送固定幂等键");
        SmokeAssert.Equal(
            "Bearer fixture-token",
            handler.CapturedAuthorization,
            "Return typed client 没有使用设备 Bearer 配对合同");

        using var oversizedHttp = new HttpClient(new OversizedReturnHandler());
        await using var oversizedClient = new MacCoreReturnClient(
            oversizedHttp,
            new Uri("http://127.0.0.1:18186/", UriKind.Absolute),
            "fixture-token");
        try
        {
            await oversizedClient.GetReturnsAsync(CancellationToken.None)
                .ConfigureAwait(false);
            throw new InvalidOperationException(
                "超过 128 KiB 的 Return 响应未被客户端拒绝。");
        }
        catch (ApiException exception)
        {
            SmokeAssert.Equal(
                "RESPONSE_TOO_LARGE",
                exception.Code,
                "超大 Return 响应没有返回稳定错误码");
            SmokeAssert.True(
                !exception.Retryable,
                "Return 合同超限不是瞬态错误，不应自动重试");
        }
    }

    private sealed class ReturnContractHandler : HttpMessageHandler
    {
        public HttpMethod? CapturedMethod { get; private set; }
        public string? CapturedPath { get; private set; }
        public bool HadContent { get; private set; }
        public string? CapturedIdempotencyKey { get; private set; }
        public string? CapturedAuthorization { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            CapturedMethod        = request.Method;
            CapturedPath          = request.RequestUri?.AbsolutePath;
            HadContent            = request.Content is not null;
            CapturedAuthorization = request.Headers.Authorization?.ToString();
            CapturedIdempotencyKey = request.Headers.TryGetValues(
                    "Idempotency-Key",
                    out var values)
                ? values.Single()
                : null;

            var payload = ReturnJson;
            if (request.Method == HttpMethod.Get
                && request.RequestUri?.AbsolutePath == "/api/v1/returns")
            {
                payload = $"[{ReturnJson}]";
            }
            var response = new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(payload, Encoding.UTF8, "application/json"),
            };
            return Task.FromResult(response);
        }
    }

    private sealed class OversizedReturnHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var response = new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new UnknownLengthContent(128 * 1024 + 1),
            };
            return Task.FromResult(response);
        }
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

    private const string ReturnJson = """
        {
          "return_id": "return-001",
          "handoff_id": "handoff-approved-001",
          "status": "contract_validated",
          "provider": "local-contract-self-test",
          "request_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "package_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "manifest_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
          "changed_file_count": 0,
          "event_count": 3,
          "validation_checks": [{"name": "return_contract", "passed": true}],
          "event_summaries": [
            {"sequence": 1, "event_type": "provider.session.started", "summary": "本地演练开始。"},
            {"sequence": 2, "event_type": "provider.progress", "summary": "正在验证。"},
            {"sequence": 3, "event_type": "provider.returned", "summary": "演练已返回。"}
          ],
          "quarantine_code": null,
          "created_at": "2026-08-05T22:02:00Z",
          "updated_at": "2026-08-05T22:02:05Z",
          "execution_notice": "仅完成合同验证；未运行 Provider、代码、测试、构建或 Git 写操作。"
        }
        """;
}
