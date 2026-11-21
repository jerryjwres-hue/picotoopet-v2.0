using System.Net;
using System.Text;
using System.Text.Json;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>仅验证真实 2.3 REST 客户端到新增 Studio 只读接口的确定性传输合同。</summary>
internal static class StudioStoryPackClientSmokeTests
{
    public static async Task RunAsync()
    {
        var handler = new StudioPreviewHandler();
        using var http = new HttpClient(handler)
        {
            BaseAddress = new Uri("http://127.0.0.1:18766/", UriKind.Absolute),
        };
        await using var client = new MacCoreClient(http, "studio-fixture-token");

        var storyPack = JsonElement.Parse("""
        {
          "schema": "picotoo.storypack.v1",
          "episode_id": "maotai_dinner",
          "title": "Maotai Dinner",
          "character_ref": "maotai_master_v1",
          "scene_ref": "dinner_room_v1",
          "style_ref": "toon_style_v1",
          "story": {"goal": "Find dinner", "payoff": "Dinner is ready"},
          "shots": [{
            "id": "S01",
            "action": "Maotai approaches his bowl",
            "state_in": "Maotai near door",
            "state_out": "Maotai near bowl",
            "because": "He smells the food"
          }]
        }
        """);

        var preview = await client.PreviewStudioStoryPackAsync(storyPack)
            .ConfigureAwait(false);

        SmokeAssert.True(handler.TotalRequests == 1, "Studio 预览不得重复提交");
        SmokeAssert.Equal(HttpMethod.Post, handler.Method, "Studio 只读预览应使用 POST body");
        SmokeAssert.Equal(
            "/api/v1/studio/storypacks/preview",
            handler.Path,
            "Windows 未使用真实 2.3 的 Studio 路由");
        SmokeAssert.Equal(
            "Bearer studio-fixture-token",
            handler.Authorization,
            "Studio 预览未复用设备 Bearer");
        SmokeAssert.Equal(
            "application/json",
            handler.ContentType,
            "预览正文必须是 JSON");
        SmokeAssert.True(
            handler.Body?.Contains("maotai_dinner", StringComparison.Ordinal) == true,
            "提交的 StoryPack 正文缺失");
        SmokeAssert.True(preview.GetProperty("can_queue").ValueKind == JsonValueKind.False,
            "只读预览被误当成 GPU 许可");
        SmokeAssert.True(
            preview.GetProperty("core23_compatibility").GetProperty("gpu_post_authorized")
                .ValueKind == JsonValueKind.False,
            "Mac Core 的 GPU HOLD 必须继续有效");

        // 非 JSON 对象、过大的包必须在网络层之前被本地拒绝。
        foreach (var invalid in new[]
        {
            JsonElement.Parse("[]"),
            JsonSerializer.SerializeToElement(new { story = new string('x', 128 * 1024) }),
        })
        {
            try
            {
                await client.PreviewStudioStoryPackAsync(invalid).ConfigureAwait(false);
                throw new InvalidOperationException("无效 StoryPack 错误地发往 Mac Core");
            }
            catch (ArgumentException)
            {
                // 预期的本地输入拒绝，不产生第二次 HTTP 请求。
            }
        }
        SmokeAssert.Equal(1, handler.TotalRequests, "输入拒绝后仍然发送了 HTTP");

        // 认证错误不得被客户端解释为成功或允许继续 Production。
        handler.RejectNext = true;
        try
        {
            await client.PreviewStudioStoryPackAsync(storyPack).ConfigureAwait(false);
            throw new InvalidOperationException("设备认证失败被当成 StoryPack 成功");
        }
        catch (ApiException error)
        {
            SmokeAssert.Equal("AUTHENTICATION_REQUIRED", error.Code,
                "客户端未正确透传 Mac Core 拒绝原因");
        }
    }

    private sealed class StudioPreviewHandler : HttpMessageHandler
    {
        public int TotalRequests { get; private set; }
        public HttpMethod? Method { get; private set; }
        public string? Path { get; private set; }
        public string? Authorization { get; private set; }
        public string? ContentType { get; private set; }
        public string? Body { get; private set; }
        public bool RejectNext { get; set; }

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            TotalRequests++;
            Method = request.Method;
            Path = request.RequestUri?.AbsolutePath;
            Authorization = request.Headers.Authorization?.ToString();
            ContentType = request.Content?.Headers.ContentType?.MediaType;
            Body = request.Content is null
                ? null
                : await request.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);

            if (RejectNext)
            {
                RejectNext = false;
                return new HttpResponseMessage(HttpStatusCode.Unauthorized)
                {
                    Content = new StringContent(
                        "{\"error\":{\"code\":\"AUTHENTICATION_REQUIRED\",\"message\":\"denied\",\"retryable\":false}}",
                        Encoding.UTF8,
                        "application/json"),
                };
            }

            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    "{\"validated\":true,\"can_queue\":false,\"core23_compatibility\":{\"mode\":\"READ_ONLY\",\"gpu_post_authorized\":false}}",
                    Encoding.UTF8,
                    "application/json"),
            };
        }
    }
}
