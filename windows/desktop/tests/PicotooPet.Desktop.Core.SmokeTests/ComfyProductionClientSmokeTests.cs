using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 ComfyUI 只允许 127.0.0.1:8188，并覆盖 object_info/prompt/history 本地协议。</summary>
internal static class ComfyProductionClientSmokeTests
{
    /// <summary>用内存 Handler 模拟本地 ComfyUI；测试不会访问网络或 GPU。</summary>
    public static async Task RunAsync()
    {
        RejectsNonFixedEndpoints();
        var handler = new FakeComfyHandler();
        using var http = new HttpClient(handler)
        {
            BaseAddress = ComfyProductionClient.FixedBaseAddress,
        };
        await using var client = new ComfyProductionClient(http);

        var objectInfo = await client.GetObjectInfoAsync().ConfigureAwait(false);
        SmokeAssert.True(objectInfo.ContainsKey("UNETLoader"), "Comfy object_info 未读取 native node。 ");

        var promptId = await client.SubmitPromptAsync(
            new JsonObject
            {
                ["1"] = new JsonObject
                {
                    ["class_type"] = "UNETLoader",
                    ["inputs"] = new JsonObject(),
                },
            }).ConfigureAwait(false);
        SmokeAssert.True(promptId == "prompt-1", "Comfy prompt_id 解析错误。");

        var history = await client.GetHistoryAsync(promptId).ConfigureAwait(false);
        SmokeAssert.True(history.ContainsKey("prompt-1"), "Comfy history 未绑定提交 prompt_id。");
        SmokeAssert.True(handler.Paths.SequenceEqual(new[] { "/object_info", "/prompt", "/history/prompt-1" }),
            "Comfy 客户端访问了未批准的本地 API 路径。");
    }

    private static void RejectsNonFixedEndpoints()
    {
        foreach (var uri in new[]
        {
            "http://localhost:8188/",
            "http://127.0.0.1:8189/",
            "https://127.0.0.1:8188/",
            "http://192.168.1.9:8188/",
        })
        {
            using var http = new HttpClient(new FakeComfyHandler()) { BaseAddress = new Uri(uri) };
            try
            {
                _ = new ComfyProductionClient(http);
                throw new InvalidOperationException($"危险 Comfy endpoint 被接受：{uri}");
            }
            catch (InvalidOperationException exception) when (
                exception.Message.Contains("COMFY_ENDPOINT_MUST_BE_LOOPBACK", StringComparison.Ordinal))
            {
                // ── 预期：正式 executor 只接受固定 IPv4 loopback ──────────────────
            }
        }
    }

    private sealed class FakeComfyHandler : HttpMessageHandler
    {
        public List<string> Paths { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var path = request.RequestUri?.AbsolutePath ?? string.Empty;
            Paths.Add(path);
            if (path == "/object_info")
            {
                return Json("{\"UNETLoader\":{},\"CLIPLoader\":{},\"VAELoader\":{}}");
            }
            if (path == "/prompt" && request.Method == HttpMethod.Post)
            {
                var body = await request.Content!.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
                SmokeAssert.True(body.Contains("\"prompt\"", StringComparison.Ordinal),
                    "Comfy prompt 请求缺少 API-format graph envelope。");
                return Json("{\"prompt_id\":\"prompt-1\",\"number\":1}");
            }
            if (path == "/history/prompt-1")
            {
                return Json("{\"prompt-1\":{\"outputs\":{}}}");
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
