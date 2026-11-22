using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
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

        // 素材走同一配对客户端；二进制字节、身份与确认头必须逐项对账。
        var assetBytes = new byte[] { 0x89, 0x50, 0x4e, 0x47, 0, 0xff };
        var assetHash = Convert.ToHexStringLower(SHA256.HashData(assetBytes));
        var expectedAssetId = "asset-" + Convert.ToHexStringLower(SHA256.HashData(
            JsonSerializer.SerializeToUtf8Bytes(new[] { "project-1", "character", assetHash })));
        var assetId = await client.ImportStudioAssetAsync(
            "project-1", "character", "image/png", assetBytes).ConfigureAwait(false);
        SmokeAssert.Equal(expectedAssetId, assetId, "资产身份必须绑定项目/角色/字节哈希");
        SmokeAssert.Equal("/api/v1/studio/assets/import", handler.Path, "资产没有使用 canonical Core API");
        SmokeAssert.Equal("Bearer studio-fixture-token", handler.Authorization, "资产未复用配对 Bearer");
        SmokeAssert.Equal("image/png", handler.ContentType, "素材不得被转换成 JSON");
        SmokeAssert.Equal("yes", handler.AssetConfirmed, "缺少明确登记确认");
        SmokeAssert.Equal(assetHash, handler.AssetDigest, "上传哈希不匹配");
        SmokeAssert.True(handler.AssetBytes?.SequenceEqual(assetBytes) == true, "上传必须保留精确文件字节");

        // 即使 HTTP 成功，任何伪造身份、篡改回执或批准字段都必须拒绝。
        foreach (var field in new[] { "artifact_id", "sha256", "size_bytes", "owner_approved",
                                     "master_approved", "can_queue", "gpu_post_authorized" })
        {
            handler.ForgedAssetField = field;
            var rejected = false;
            try
            {
                await client.ImportStudioAssetAsync(
                    "project-1", "character", "image/png", assetBytes).ConfigureAwait(false);
            }
            catch (InvalidOperationException)
            {
                rejected = true;
            }
            SmokeAssert.True(rejected, $"伪造资产回执字段 {field} 不得绑定草稿");
        }
        handler.ForgedAssetField = null;

        var previousRequests = handler.TotalRequests;
        try
        {
            await client.ImportStudioAssetAsync(
                "project-1", "character", "text/plain", assetBytes).ConfigureAwait(false);
            throw new InvalidOperationException("非法角色 MIME 错误发往 Core");
        }
        catch (ArgumentException)
        {
            // 客户端应拒绝不符合合同的输入。
        }
        SmokeAssert.Equal(previousRequests, handler.TotalRequests, "非法素材不应发出 HTTP 请求");
        Console.WriteLine("STUDIO_ASSET_BYTE_TRANSPORT=PASS; RECEIPT_FAIL_CLOSED=PASS");
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
        public byte[]? AssetBytes { get; private set; }
        public string? AssetConfirmed { get; private set; }
        public string? AssetDigest { get; private set; }
        public string? ForgedAssetField { get; set; }

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            TotalRequests++;
            Method = request.Method;
            Path = request.RequestUri?.AbsolutePath;
            Authorization = request.Headers.Authorization?.ToString();
            ContentType = request.Content?.Headers.ContentType?.MediaType;
            if (Path == "/api/v1/studio/assets/import")
            {
                var project = request.Headers.GetValues("X-Picotoo-Project-Id").Single();
                var role = request.Headers.GetValues("X-Picotoo-Asset-Role").Single();
                AssetConfirmed = request.Headers.GetValues("X-Picotoo-Import-Confirmed").Single();
                AssetDigest = request.Headers.GetValues("X-Picotoo-Asset-SHA256").Single();
                var bytes = await request.Content!.ReadAsByteArrayAsync(cancellationToken).ConfigureAwait(false);
                AssetBytes = bytes;
                var digest = Convert.ToHexStringLower(SHA256.HashData(bytes));
                var id = "asset-" + Convert.ToHexStringLower(SHA256.HashData(
                    JsonSerializer.SerializeToUtf8Bytes(new[] { project, role, digest })));
                var receipt = JsonNode.Parse(JsonSerializer.Serialize(new
                {
                    contract = "picotoo.storypack.local-asset-intake.v1",
                    artifact_id = id, project_id = project, role, sha256 = digest,
                    media_type = ContentType, size_bytes = bytes.Length, registration = "CREATED",
                    content_integrity_verified = true,
                    source_provenance = "OPERATOR_SUBMITTED_COPY_UNVERIFIED",
                    cloud_policy = "local_only", is_original = false, owner_approved = false,
                    master_approved = false, can_queue = false, gpu_post_authorized = false,
                }))!.AsObject();
                if (ForgedAssetField is { } field)
                {
                    receipt[field] = field switch
                    {
                        "artifact_id" => JsonValue.Create("asset-" + new string('0', 64)),
                        "sha256" => JsonValue.Create(new string('0', 64)),
                        "size_bytes" => JsonValue.Create(-1),
                        _ => JsonValue.Create(true),
                    };
                }
                return new HttpResponseMessage(HttpStatusCode.Created)
                {
                    Content = new StringContent(receipt.ToJsonString(), Encoding.UTF8, "application/json"),
                };
            }

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
