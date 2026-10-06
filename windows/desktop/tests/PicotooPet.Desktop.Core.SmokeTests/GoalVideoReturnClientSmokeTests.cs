using System.Net;
using System.Text;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 C001 POST/GET 路径、裸对象 body、认证和有界错误。</summary>
internal static class GoalVideoReturnClientSmokeTests
{
    public static async Task RunAsync()
    {
        var handler = new RecordingHandler();
        using var http = new HttpClient(handler)
        {
            BaseAddress = new Uri("http://127.0.0.1:8765/"),
        };
        await using var client = new MacCoreClient(http, "fixture-token");
        var payload = GoalVideoReturnParser.Parse(
            "{\"goal_id\":\"goal / 1\",\"nested\":{\"value\":\"原样\"}}");

        var submitted = await client.SubmitGoalVideoReturnAsync(
            "goal / 1",
            payload,
            CancellationToken.None).ConfigureAwait(false);
        var refreshed = await client.GetGoalVideoContinuationAsync(
            "goal / 1",
            CancellationToken.None).ConfigureAwait(false);

        SmokeAssert.Equal("production-job", submitted.ProductionJobId, "POST continuation 响应错误");
        SmokeAssert.Equal("creative_ready", refreshed.CreativeStatus, "GET continuation 响应错误");
        SmokeAssert.True(
            handler.Requests.Select(item => $"{item.Method} {item.Path}").SequenceEqual(
            [
                "POST /api/v1/autonomous/goals/goal%20%2F%201/handoff/video-return",
                "GET /api/v1/autonomous/goals/goal%20%2F%201/handoff/video-return",
            ]),
            "视频返回客户端访问了错误路径");
        var post = handler.Requests[0];
        SmokeAssert.Equal("Bearer fixture-token", post.Authorization, "POST 未复用 Bearer auth");
        SmokeAssert.True(!string.IsNullOrWhiteSpace(post.TraceId), "POST 未复用 trace header");
        SmokeAssert.True(post.Body.StartsWith("{\"goal_id\"", StringComparison.Ordinal), "POST body 被包装");
        SmokeAssert.True(!post.Body.Contains("payload", StringComparison.OrdinalIgnoreCase), "POST body 出现包装字段");

        await Assert409Async(payload).ConfigureAwait(false);
        await AssertBoundedResponseAsync(payload).ConfigureAwait(false);
    }

    private static async Task Assert409Async(System.Text.Json.JsonElement payload)
    {
        using var http = new HttpClient(new ConflictHandler())
        {
            BaseAddress = new Uri("http://127.0.0.1:8765/"),
        };
        await using var client = new MacCoreClient(http, "fixture-token");
        try
        {
            _ = await client.SubmitGoalVideoReturnAsync("goal-1", payload).ConfigureAwait(false);
            throw new InvalidOperationException("409 必须暴露为 ApiException");
        }
        catch (ApiException exception)
        {
            SmokeAssert.Equal(409, exception.StatusCode, "409 status 丢失");
            SmokeAssert.True(!exception.Retryable, "409 不得标成可重试");
        }
    }

    private static async Task AssertBoundedResponseAsync(System.Text.Json.JsonElement payload)
    {
        using var http = new HttpClient(new OversizedHandler())
        {
            BaseAddress = new Uri("http://127.0.0.1:8765/"),
        };
        await using var client = new MacCoreClient(http, "fixture-token");
        try
        {
            _ = await client.SubmitGoalVideoReturnAsync("goal-1", payload).ConfigureAwait(false);
            throw new InvalidOperationException("超大 continuation 响应必须拒绝");
        }
        catch (ApiException exception)
        {
            SmokeAssert.Equal("RESPONSE_TOO_LARGE", exception.Code, "超大响应错误码不正确");
        }
    }

    private sealed class RecordingHandler : HttpMessageHandler
    {
        public List<CapturedRequest> Requests { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            Requests.Add(new CapturedRequest(
                request.Method.Method,
                request.RequestUri?.AbsolutePath ?? string.Empty,
                request.Headers.Authorization?.ToString() ?? string.Empty,
                request.Headers.TryGetValues("X-Picotoo-Trace-Id", out var traceIds)
                    ? traceIds.Single()
                    : string.Empty,
                request.Content is null
                    ? string.Empty
                    : await request.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false)));
            return Json(HttpStatusCode.OK, ContinuationJson);
        }
    }

    private sealed class ConflictHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken) =>
            Task.FromResult(Json(
                HttpStatusCode.Conflict,
                "{\"error\":{\"code\":\"AUTONOMOUS_VIDEO_RETURN_CONFLICT\",\"message\":\"conflict\",\"retryable\":false,\"trace_id\":\"trace-409\"}}"));
    }

    private sealed class OversizedHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    "{\"padding\":\"" + new string('x', 70_000) + "\"}",
                    Encoding.UTF8,
                    "application/json"),
            });
    }

    private static HttpResponseMessage Json(HttpStatusCode status, string content) =>
        new(status)
        {
            Content = new StringContent(content, Encoding.UTF8, "application/json"),
        };

    private sealed record CapturedRequest(
        string Method,
        string Path,
        string Authorization,
        string TraceId,
        string Body);

    private const string ContinuationJson = """
        {
          "goal_id":"goal / 1",
          "handoff_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "return_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "creative_job_id":"creative-job",
          "creative_package_id":"11111111-1111-4111-8111-111111111111",
          "creative_package_digest":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
          "creative_status":"creative_ready",
          "production_job_id":"production-job",
          "production_status":"Ready"
        }
        """;
}
