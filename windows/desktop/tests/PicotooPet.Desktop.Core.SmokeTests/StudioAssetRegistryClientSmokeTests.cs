using System.Globalization;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验收 Windows 的 LoRA 摘要登记及待审批请求；只发送合成字节哈希。</summary>
internal static class StudioAssetRegistryClientSmokeTests
{
    public static async Task RunAsync()
    {
        // 01. 只发送 SHA / 文件名，不允许整个 LoRA 文件或 D: 路径上网。
        var handler = new RegistryStub();
        using var http = new HttpClient(handler)
        {
            BaseAddress = new Uri("http://127.0.0.1:18766/", UriKind.Absolute),
        };
        await using var client = new MacCoreClient(http, "registry-fixture-token");
        const string sha = "5972e7f782e3e4ed16b764441fdb66d638cb6a8ba85fb8226d95feeb98e8eb70";
        const long bytes = 46_223_616;
        var evidence = new StudioWindowsByteEvidence(
            "maotai_lora_v2.safetensors",
            DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture));
        var expectedId = "asset-" + Convert.ToHexStringLower(SHA256.HashData(
            JsonSerializer.SerializeToUtf8Bytes(new[] { "project-1", "lora", sha })));
        var record = await client.RegisterStudioWindowsLoraAsync(
            "project-1", sha, bytes, evidence).ConfigureAwait(false);
        SmokeAssert.Equal(expectedId, record.ArtifactId, "Core 资产 ID 不可仅相信远端回执");
        SmokeAssert.Equal("/api/v1/studio/assets/windows-evidence", handler.Path,
            "Windows LoRA 必须走新的只存摘要端点");
        SmokeAssert.Equal("Bearer registry-fixture-token", handler.Authorization,
            "LoRA 未通过现有设备 Bearer");
        SmokeAssert.Equal("application/json", handler.ContentType, "LoRA 不得直接上传二进制");
        SmokeAssert.True(!handler.Body!.Contains("D:\\", StringComparison.OrdinalIgnoreCase),
            "登记请求不能包含 Windows 私有目录");
        SmokeAssert.True(!handler.Body.Contains("file_path", StringComparison.OrdinalIgnoreCase),
            "登记请求不能携带文件路径");
        var uploaded = JsonElement.Parse(handler.Body);
        SmokeAssert.Equal(bytes, uploaded.GetProperty("size_bytes").GetInt64(),
            "Core 的 LoRA 大小不能编造");
        SmokeAssert.Equal(sha, uploaded.GetProperty("sha256").GetString(), "LoRA 完整 SHA 未发送");
        SmokeAssert.Equal(evidence.FileName,
            uploaded.GetProperty("windows_evidence").GetProperty("file_name").GetString(),
            "声明只能包含 basename");
        SmokeAssert.True(uploaded.GetProperty("confirmed").ValueKind == JsonValueKind.True,
            "登记必须由 Windows 用户点击明确确认");
        SmokeAssert.True(record.Evidence == evidence, "不得悄悄更换核验时间或来源");

        // 02. LoRA 登记后，必须第二次独立调用才创建 Pending，决不审批。
        SmokeAssert.Equal(1, handler.RequestCount, "一次登记不得自动发起 Owner 审批");
        var approval = await client.RequestStudioAssetOwnerApprovalAsync(
            record.ArtifactId, sha, record.Evidence).ConfigureAwait(false);
        SmokeAssert.Equal("Pending", approval.Status, "未获 Owner 决定不得宣称 Approved");
        SmokeAssert.Equal(expectedId, approval.ArtifactId, "审批必须绑定同一资产");
        SmokeAssert.Equal("/api/v1/studio/assets/" + expectedId + "/owner-approval-request",
            handler.Path, "审批必须复用现有 Core 路由");
        var request = JsonElement.Parse(handler.Body!);
        SmokeAssert.Equal(sha, request.GetProperty("expected_sha256").GetString(),
            "待审应绑定原始 LoRA 字节 SHA");
        SmokeAssert.Equal(evidence.VerifiedAt,
            request.GetProperty("windows_evidence").GetProperty("verified_at").GetString(),
            "待审范围不能变更 Windows 核验时间");
        SmokeAssert.True(request.GetProperty("windows_evidence").ValueKind == JsonValueKind.Object,
            "Windows 申报 LoRA 不可冒充 Core 已验文件");
        SmokeAssert.Equal(2, handler.RequestCount, "登记和待审必须分成两条网络请求");

        // 03. 已由 Core 哈希的图片/身份锁不得附加 Windows LoRA 声明。
        await client.RequestStudioAssetOwnerApprovalAsync(expectedId, sha, null)
            .ConfigureAwait(false);
        var noEvidence = JsonElement.Parse(handler.Body!);
        SmokeAssert.True(noEvidence.GetProperty("windows_evidence").ValueKind == JsonValueKind.Null,
            "Core 已核验素材的 Owner 请求不能附带 Windows 声明");

        // 04. 输入先在本地封锁；绝不联网发送非法路径、假短 SHA、零字节。
        var requests = handler.RequestCount;
        foreach (var invalid in new[] {
            new StudioWindowsByteEvidence("D:\\private\\lora.safetensors", evidence.VerifiedAt),
            new StudioWindowsByteEvidence("lora.safetensors", evidence.VerifiedAt,
                                          Verifier: "untrusted-fake-verifier"),
        })
        {
            var rejected = false;
            try { await client.RegisterStudioWindowsLoraAsync("project-1", sha, bytes, invalid); }
            catch (ArgumentException) { rejected = true; }
            SmokeAssert.True(rejected, "禁止路径或伪造核验者");
        }
        foreach (var bad in new[] { "00", new string('Z', 64), new string('A', 64) })
        {
            var rejected = false;
            try { await client.RegisterStudioWindowsLoraAsync("project-1", bad, bytes, evidence); }
            catch (ArgumentException) { rejected = true; }
            SmokeAssert.True(rejected, "必须只接受完整小写 SHA256");
        }
        foreach (var badBytes in new long[] { 0, -1, 4L * 1024 * 1024 * 1024 + 1 })
        {
            var rejected = false;
            try { await client.RegisterStudioWindowsLoraAsync("project-1", sha, badBytes, evidence); }
            catch (ArgumentException) { rejected = true; }
            SmokeAssert.True(rejected, "LoRA 元数据边界必须生效");
        }
        SmokeAssert.Equal(requests, handler.RequestCount,
            "拒绝非法 Windows LoRA 信息后仍然网络提交");

        // 05. 所有伪造回执字段都必须 fail closed，不能当成功资产。
        foreach (var field in new[] { "artifact_id", "sha256", "size_bytes",
                                       "owner_approved", "core_verified_bytes",
                                       "can_queue", "gpu_post_authorized",
                                       "byte_provenance", "windows_evidence" })
        {
            handler.ForgeField = field;
            var rejected = false;
            try { await client.RegisterStudioWindowsLoraAsync("project-1", sha, bytes, evidence); }
            catch (InvalidOperationException) { rejected = true; }
            SmokeAssert.True(rejected, "伪造 Windows LoRA 登记回执未被拒绝: " + field);
        }
        handler.ForgeField = null;

        // 06. 请求审批回执同样不能伪造已通过或授权 GPU。
        foreach (var field in new[] { "artifact_id", "status", "request_digest",
                                       "approval_type", "gpu_post_authorized" })
        {
            handler.ForgeField = field;
            var rejected = false;
            try { await client.RequestStudioAssetOwnerApprovalAsync(expectedId, sha, evidence); }
            catch (InvalidOperationException) { rejected = true; }
            SmokeAssert.True(rejected, "伪造待审回执未被拒绝: " + field);
        }
        handler.ForgeField = null;

        // 07. 对错误 Bearer 的拒绝必须来自真实客户端错误路径，不得转成可用 ID。
        handler.RejectNext = true;
        var denied = false;
        try { await client.RegisterStudioWindowsLoraAsync("project-1", sha, bytes, evidence); }
        catch (ApiException error)
        {
            denied = error.StatusCode == 401 && error.Code == "AUTHENTICATION_REQUIRED";
        }
        SmokeAssert.True(denied, "无效设备令牌不得被当作登记成功");
        Console.WriteLine("WINDOWS_LORA_SHA_CLAIM=PASS; OWNER_REQUEST_PENDING=PASS; GPU_POST=0");
    }

    private sealed class RegistryStub : HttpMessageHandler
    {
        public int RequestCount { get; private set; }
        public string? Path { get; private set; }
        public string? Authorization { get; private set; }
        public string? ContentType { get; private set; }
        public string? Body { get; private set; }
        public string? ForgeField { get; set; }
        public bool RejectNext { get; set; }

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            RequestCount++;
            Path = request.RequestUri?.AbsolutePath;
            Authorization = request.Headers.Authorization?.ToString();
            ContentType = request.Content?.Headers.ContentType?.MediaType;
            Body = await request.Content!.ReadAsStringAsync(cancellationToken);
            if (RejectNext)
            {
                RejectNext = false;
                return new HttpResponseMessage(HttpStatusCode.Unauthorized)
                {
                    Content = new StringContent(
                        """{"error":{"code":"AUTHENTICATION_REQUIRED","message":"denied","retryable":false}}""",
                        Encoding.UTF8, "application/json"),
                };
            }

            JsonObject reply;
            if (Path == "/api/v1/studio/assets/windows-evidence")
            {
                var input = JsonElement.Parse(Body);
                var project = input.GetProperty("project_id").GetString()!;
                var sha = input.GetProperty("sha256").GetString()!;
                var id = "asset-" + Convert.ToHexStringLower(SHA256.HashData(
                    JsonSerializer.SerializeToUtf8Bytes(new[] { project, "lora", sha })));
                reply = JsonSerializer.SerializeToNode(new
                {
                    contract = "picotoo.storypack.windows-byte-claim.v1",
                    artifact_id = id, project_id = project, asset_kind = "lora",
                    sha256 = sha, size_bytes = input.GetProperty("size_bytes").GetInt64(),
                    media_type = "application/octet-stream", registration = "CREATED",
                    byte_provenance = "WINDOWS_CLIENT_CLAIM_NOT_CORE_HASHED",
                    core_verified_bytes = false, owner_approved = false,
                    can_queue = false, gpu_post_authorized = false,
                    windows_evidence = JsonSerializer.Deserialize<JsonElement>(
                        input.GetProperty("windows_evidence").GetRawText()),
                })!.AsObject();
            }
            else if (Path?.EndsWith("/owner-approval-request", StringComparison.Ordinal) == true)
            {
                reply = JsonSerializer.SerializeToNode(new
                {
                    approval_id = "synthetic-approval-1",
                    approval_type = "storypack.asset_owner_approval.v1",
                    request_digest = new string('a', 64),
                    status = "Pending",
                    artifact_id = Path.Split('/')[5],
                    registration = "CREATED",
                    owner_approved = false,
                    gpu_post_authorized = false,
                })!.AsObject();
            }
            else
            {
                throw new InvalidOperationException("Unexpected registry URL: " + Path);
            }

            if (ForgeField is { } field)
            {
                reply[field] = field switch
                {
                    "artifact_id" => JsonValue.Create("asset-" + new string('0', 64)),
                    "sha256" => JsonValue.Create(new string('f', 64)),
                    "request_digest" => JsonValue.Create("INVALID_DIGEST"),
                    "size_bytes" => JsonValue.Create(-1),
                    "owner_approved" or "gpu_post_authorized" or "core_verified_bytes" =>
                        JsonValue.Create(true),
                    "byte_provenance" or "approval_type" => JsonValue.Create("FAKE"),
                    "status" => JsonValue.Create("Approved"),
                    "windows_evidence" => JsonSerializer.SerializeToNode(
                        new { file_name = "forged.safetensors" }),
                    _ => JsonValue.Create("FAKE"),
                };
            }
            return new HttpResponseMessage(HttpStatusCode.Created)
            {
                Content = new StringContent(reply.ToJsonString(), Encoding.UTF8, "application/json"),
            };
        }
    }
}
