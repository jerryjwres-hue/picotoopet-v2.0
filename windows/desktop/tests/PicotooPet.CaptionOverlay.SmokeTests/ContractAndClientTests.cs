using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.CaptionOverlay.SmokeTests;

/// <summary>Contracts + GET 客户端：路径/转义/鉴权/trace/有界/严格/错误不泄露文案。</summary>
internal static class ContractAndClientTests
{
    private const string Secret = "SECRET-OVERLAY-TEXT-请勿泄露";

    public static async Task RunAsync()
    {
        var sample = await File.ReadAllBytesAsync(
            Path.Combine(AppContext.BaseDirectory, "SamplePlanResponse.json")).ConfigureAwait(false);

        // 与 Python Core 生成的真实响应逐字节对齐：规范 JSON digest 必须一致。
        var parsed = CaptionOverlayPlanParser.Parse(sample);
        SmokeAssert.Equal("job-1", parsed.Plan.ProductionJobId, "样例 job id");
        SmokeAssert.Equal(2, parsed.Plan.Overlays.Count, "样例 overlay 数");
        SmokeAssert.Equal("快速干燥，轻松护理", parsed.Plan.Overlays[1].Text, "中文文案必须原样保留");

        // digest 被篡改 / 文案被篡改 / 多余字段 → PLAN_INVALID。
        var node = JsonNode.Parse(sample)!;
        node["caption_overlay_plan_digest"] = new string('0', 64);
        ExpectInvalid(node.ToJsonString(), "digest 不匹配必须拒绝");

        node = JsonNode.Parse(sample)!;
        node["plan"]!["overlays"]![0]!["text"] = "tampered";
        ExpectInvalid(node.ToJsonString(), "文案与 text_sha256 不一致必须拒绝");

        node = JsonNode.Parse(sample)!;
        node["plan"]!["font_path"] = "C:\\Windows\\Fonts\\arial.ttf";
        ExpectInvalid(node.ToJsonString(), "额外字段（字体路径）必须拒绝");

        node = JsonNode.Parse(sample)!;
        node["plan"]!["output_profile_id"] = "video.custom.v1";
        ExpectInvalid(node.ToJsonString(), "未知输出档位必须拒绝");

        node = JsonNode.Parse(sample)!;
        node["plan"]!["overlays"]![1]!["start_ms"] = 100;
        ExpectInvalid(node.ToJsonString(), "cue 起点倒退必须拒绝");

        // 客户端：精确路径、转义、鉴权、trace。
        var handler = new RecordingHandler(HttpStatusCode.OK, sample);
        using var http = new HttpClient(handler) { BaseAddress = new Uri("http://mac.local:8787/") };
        var client = new MacCoreCaptionOverlayClient(http, "token-abc");
        var plan = await client.GetCaptionOverlayPlanAsync("job-1", CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal("job-1", plan.Plan.ProductionJobId, "客户端解析");
        SmokeAssert.Equal(
            "/api/v1/postproduction/production/job-1/caption-overlay-plan",
            handler.LastRequest!.RequestUri!.AbsolutePath,
            "精确 GET 路径");
        SmokeAssert.Equal(HttpMethod.Get, handler.LastRequest.Method, "必须是 GET");
        SmokeAssert.Equal("Bearer token-abc", handler.LastAuthorization, "必须携带 Bearer");
        SmokeAssert.True(!string.IsNullOrEmpty(handler.LastTraceId), "必须带 X-Picotoo-Trace-Id");

        // job id 响应绑定：URL 的 job 与响应不同必须拒绝。
        await SmokeAssert.ThrowsCodeAsync(
            () => client.GetCaptionOverlayPlanAsync("other-job", CancellationToken.None),
            TextOverlayException.PlanInvalid,
            "响应 job 与请求不一致必须拒绝").ConfigureAwait(false);

        // URL 转义。
        var escapeHandler = new RecordingHandler(HttpStatusCode.OK, sample);
        using var escapeHttp = new HttpClient(escapeHandler) { BaseAddress = new Uri("http://mac.local:8787/") };
        try
        {
            await new MacCoreCaptionOverlayClient(escapeHttp, "t")
                .GetCaptionOverlayPlanAsync("a/b c?x=1", CancellationToken.None).ConfigureAwait(false);
        }
        catch (TextOverlayException)
        {
            // 响应 job 不匹配是预期的；这里只验证请求 URL。
        }
        SmokeAssert.True(
            escapeHandler.LastRequest!.RequestUri!.AbsoluteUri.Contains("a%2Fb%20c%3Fx%3D1", StringComparison.Ordinal),
            "production_job_id 必须 URL 转义");

        // 有界响应。
        var huge = new RecordingHandler(HttpStatusCode.OK, new byte[MacCoreCaptionOverlayClient.MaxResponseBytes + 1]);
        using var hugeHttp = new HttpClient(huge) { BaseAddress = new Uri("http://mac.local:8787/") };
        try
        {
            await new MacCoreCaptionOverlayClient(hugeHttp, "t")
                .GetCaptionOverlayPlanAsync("job-1", CancellationToken.None).ConfigureAwait(false);
            throw new InvalidOperationException("超大响应必须拒绝");
        }
        catch (ApiException exception)
        {
            SmokeAssert.Equal("CAPTION_OVERLAY_RESPONSE_TOO_LARGE", exception.Code, "超大响应错误码");
        }

        // 类型化有界 API 错误：只采用 [A-Z0-9_] 错误码，正文（含文案）永不外泄。
        var errorBody = Encoding.UTF8.GetBytes(
            "{\"error\":{\"code\":\"TEXT_PRESENTATION_NOT_READY\",\"message\":\"" + Secret + "\",\"retryable\":true,\"trace_id\":\"t\"}}");
        var notReady = new RecordingHandler(HttpStatusCode.Conflict, errorBody);
        using var notReadyHttp = new HttpClient(notReady) { BaseAddress = new Uri("http://mac.local:8787/") };
        try
        {
            await new MacCoreCaptionOverlayClient(notReadyHttp, "t")
                .GetCaptionOverlayPlanAsync("job-1", CancellationToken.None).ConfigureAwait(false);
            throw new InvalidOperationException("409 必须抛出");
        }
        catch (ApiException exception)
        {
            SmokeAssert.Equal("TEXT_PRESENTATION_NOT_READY", exception.Code, "错误码保留");
            SmokeAssert.True(exception.Retryable, "NOT_READY 可重试");
            SmokeAssert.Equal(409, exception.StatusCode, "HTTP 状态");
            SmokeAssert.True(!exception.Message.Contains(Secret, StringComparison.Ordinal), "错误消息不得含文案");
        }

        var hostile = new RecordingHandler(
            HttpStatusCode.InternalServerError,
            Encoding.UTF8.GetBytes("{\"error\":{\"code\":\"lower case <script> " + Secret + "\"}}"));
        using var hostileHttp = new HttpClient(hostile) { BaseAddress = new Uri("http://mac.local:8787/") };
        try
        {
            await new MacCoreCaptionOverlayClient(hostileHttp, "t")
                .GetCaptionOverlayPlanAsync("job-1", CancellationToken.None).ConfigureAwait(false);
            throw new InvalidOperationException("500 必须抛出");
        }
        catch (ApiException exception)
        {
            SmokeAssert.Equal("CAPTION_OVERLAY_HTTP_ERROR", exception.Code, "非法错误码回落为通用码");
            SmokeAssert.True(!exception.Message.Contains(Secret, StringComparison.Ordinal), "回落消息不得含文案");
        }
    }

    private static void ExpectInvalid(string json, string message)
    {
        try
        {
            CaptionOverlayPlanParser.Parse(Encoding.UTF8.GetBytes(json));
        }
        catch (TextOverlayException exception)
        {
            SmokeAssert.Equal(TextOverlayException.PlanInvalid, exception.Code, message);
            return;
        }
        throw new InvalidOperationException($"{message}（未抛出）");
    }

    private sealed class RecordingHandler : HttpMessageHandler
    {
        private readonly HttpStatusCode _status;
        private readonly byte[] _body;

        public RecordingHandler(HttpStatusCode status, byte[] body)
        {
            _status = status;
            _body = body;
        }

        public HttpRequestMessage? LastRequest { get; private set; }
        public string? LastAuthorization { get; private set; }
        public string? LastTraceId { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            LastRequest = request;
            LastAuthorization = request.Headers.Authorization?.ToString();
            LastTraceId = request.Headers.TryGetValues("X-Picotoo-Trace-Id", out var values) ? values.FirstOrDefault() : null;
            return Task.FromResult(new HttpResponseMessage(_status) { Content = new ByteArrayContent(_body) });
        }
    }
}
