using System.Security.Cryptography;
using System.Text.Json;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>Windows 本机文件摘要证明；只记录文件名，不包含私有 Windows 路径。</summary>
public sealed record StudioWindowsByteEvidence(
    string FileName,
    string VerifiedAt,
    string Verifier = "windows-studio-selected-local-file");

/// <summary>Core 记录的是 Windows 摘要声明，不是 Mac 已验字节或生产授权。</summary>
public sealed record StudioWindowsClaimReceipt(
    string ArtifactId,
    string Sha256,
    long SizeBytes,
    StudioWindowsByteEvidence Evidence);

/// <summary>待审批登记回执；只能由现有审批中心作出 Owner 决定。</summary>
public sealed record StudioOwnerApprovalRequestReceipt(
    string ArtifactId,
    string ApprovalId,
    string RequestDigest,
    string Status);

public sealed partial class MacCoreClient
{
    private const int StudioRegistryResponseLimit = 24 * 1024;
    private const long StudioLoraMaxBytes = 4L * 1024 * 1024 * 1024;

    /// <summary>验证只读文件摘要后，只把摘要、大小及文件名发送给 Mac Core。</summary>
    public async Task<StudioWindowsClaimReceipt> RegisterStudioWindowsLoraAsync(
        string projectId, string sha256, long sizeBytes,
        StudioWindowsByteEvidence evidence,
        CancellationToken cancellationToken = default)
    {
        // 01. 与真实 Core P0-1 接口使用相同的角色与摘要限制。
        //     不接受任何目录路径、设备口令、网络 URL 或文件内容。
        ArgumentNullException.ThrowIfNull(evidence);
        ValidateStudioRegistryProject(projectId);
        ValidateStudioRegistryHash(sha256);
        ValidateStudioWindowsEvidence(evidence);
        if (sizeBytes is <= 0 or > StudioLoraMaxBytes)
        {
            throw new ArgumentException("LoRA 文件大小不符合现有资产登记合同。");
        }

        var expectedId = StudioRegistryAssetId(projectId, "lora", sha256);
        var claim = new
        {
            project_id = projectId,
            asset_kind = "lora",
            sha256,
            size_bytes = sizeBytes,
            media_type = "application/octet-stream",
            windows_evidence = StudioEvidenceBody(evidence),
            confirmed = true,
        };
        // 02. 复用配对连接和已有错误/响应大小限制，永不上传 LoRA bytes。
        var receipt = await SendAsync<JsonElement>(
            HttpMethod.Post, "api/v1/studio/assets/windows-evidence", claim,
            "studio.asset.windows-evidence", null, cancellationToken,
            StudioRegistryResponseLimit).ConfigureAwait(false);
        var serverEvidence = receipt.TryGetProperty("windows_evidence", out var found)
            ? found : default;
        if (!StudioRegistryString(receipt, "contract", "picotoo.storypack.windows-byte-claim.v1")
            || !StudioRegistryString(receipt, "artifact_id", expectedId)
            || !StudioRegistryString(receipt, "project_id", projectId)
            || !StudioRegistryString(receipt, "asset_kind", "lora")
            || !StudioRegistryString(receipt, "sha256", sha256)
            || !StudioRegistryString(receipt, "media_type", "application/octet-stream")
            || !StudioRegistryString(receipt, "byte_provenance",
                                     "WINDOWS_CLIENT_CLAIM_NOT_CORE_HASHED")
            || !StudioRegistryStringIn(receipt, "registration", "CREATED", "REPLAY")
            || !StudioRegistryLong(receipt, "size_bytes", sizeBytes)
            || !StudioRegistryBool(receipt, "core_verified_bytes", false)
            || !StudioRegistryBool(receipt, "owner_approved", false)
            || !StudioRegistryBool(receipt, "can_queue", false)
            || !StudioRegistryBool(receipt, "gpu_post_authorized", false)
            || !StudioRegistryString(serverEvidence, "method", "windows_full_file_sha256")
            || !StudioRegistryString(serverEvidence, "file_name", evidence.FileName)
            || !StudioRegistryString(serverEvidence, "verifier", evidence.Verifier)
            || !StudioRegistryString(serverEvidence, "verified_at", evidence.VerifiedAt))
        {
            throw new InvalidOperationException(
                "Windows 摘要登记回执不可信；禁止绑定或发起后续批准。");
        }
        return new StudioWindowsClaimReceipt(expectedId, sha256, sizeBytes, evidence);
    }

    /// <summary>仅创建现有 Owner 审批中心的待处理请求，不能代替主人点击批准。</summary>
    public async Task<StudioOwnerApprovalRequestReceipt> RequestStudioAssetOwnerApprovalAsync(
        string artifactId, string sha256, StudioWindowsByteEvidence? windowsEvidence,
        CancellationToken cancellationToken = default)
    {
        // 03. 显式输入资产 UUID-like identity 和 SHA，拒绝任何路径查询或假 ID。
        ValidateStudioRegistryArtifactId(artifactId);
        ValidateStudioRegistryHash(sha256);
        if (windowsEvidence is not null)
        {
            ValidateStudioWindowsEvidence(windowsEvidence);
        }
        var request = new
        {
            expected_sha256 = sha256,
            windows_evidence = windowsEvidence is null
                ? null : StudioEvidenceBody(windowsEvidence),
            expires_seconds = 3600,
        };
        var receipt = await SendAsync<JsonElement>(
            HttpMethod.Post,
            $"api/v1/studio/assets/{artifactId}/owner-approval-request", request,
            "studio.asset.owner-approval-request", null, cancellationToken,
            StudioRegistryResponseLimit).ConfigureAwait(false);
        // 04. A previous approval may return Approved on idempotent replay;
        //     never claim that a NEW approval occurred or allow GPU work.
        var status = StudioRegistryReadString(receipt, "status");
        var alreadyApproved = string.Equals(status, "Approved", StringComparison.Ordinal);
        var approvalId = StudioRegistryReadString(receipt, "approval_id");
        var digest = StudioRegistryReadString(receipt, "request_digest");
        if (!StudioRegistryString(receipt, "approval_type", "storypack.asset_owner_approval.v1")
            || !StudioRegistryString(receipt, "artifact_id", artifactId)
            || !StudioRegistryStringIn(receipt, "registration", "CREATED", "REPLAY")
            || !StudioRegistryBool(receipt, "owner_approved", alreadyApproved)
            || !StudioRegistryBool(receipt, "gpu_post_authorized", false)
            || !(status is "Pending" or "Approved")
            || string.IsNullOrWhiteSpace(approvalId)
            || !StudioRegistryIsSha(digest))
        {
            throw new InvalidOperationException(
                "待审批回执不可信；不能显示为已提交或已批准。");
        }
        return new StudioOwnerApprovalRequestReceipt(artifactId, approvalId, digest, status!);
    }

    private static object StudioEvidenceBody(StudioWindowsByteEvidence evidence) => new
    {
        method = "windows_full_file_sha256",
        verified_at = evidence.VerifiedAt,
        verifier = evidence.Verifier,
        file_name = evidence.FileName,
    };

    private static string StudioRegistryAssetId(string projectId, string role, string sha256)
    {
        var scope = JsonSerializer.SerializeToUtf8Bytes(new[] { projectId, role, sha256 });
        return "asset-" + Convert.ToHexStringLower(SHA256.HashData(scope));
    }

    private static void ValidateStudioRegistryProject(string projectId)
    {
        if (string.IsNullOrWhiteSpace(projectId) || projectId.Length > 100
            || projectId.Any(c => !(char.IsAsciiLetterOrDigit(c) || c is '-' or '_')))
        {
            throw new ArgumentException("无效项目 ID。", nameof(projectId));
        }
    }

    private static void ValidateStudioRegistryHash(string value)
    {
        if (!StudioRegistryIsSha(value))
        {
            throw new ArgumentException("必须提供完整小写 SHA256。", nameof(value));
        }
    }

    private static bool StudioRegistryIsSha(string? value) =>
        value is { Length: 64 } && value.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static void ValidateStudioRegistryArtifactId(string id)
    {
        if (id is not { Length: 70 } || !id.StartsWith("asset-", StringComparison.Ordinal)
            || !StudioRegistryIsSha(id[6..]))
        {
            throw new ArgumentException("无效 Core 资产 ID。", nameof(id));
        }
    }

    private static void ValidateStudioWindowsEvidence(StudioWindowsByteEvidence evidence)
    {
        if (evidence.FileName is not { Length: > 0 and <= 255 }
            || evidence.FileName != evidence.FileName.Trim()
            || evidence.FileName is "." or ".."
            || evidence.FileName.Any(c => c is '/' or '\\' or ':' || char.IsControl(c))
            || evidence.Verifier is not "windows-studio-selected-local-file"
            || !DateTimeOffset.TryParse(
                evidence.VerifiedAt, System.Globalization.CultureInfo.InvariantCulture,
                System.Globalization.DateTimeStyles.AssumeUniversal, out var timestamp)
            || timestamp.Offset != TimeSpan.Zero
            || timestamp > DateTimeOffset.UtcNow.AddMinutes(2)
            || timestamp < DateTimeOffset.UtcNow.AddDays(-1))
        {
            throw new ArgumentException("本机摘要证据格式无效。", nameof(evidence));
        }
    }

    private static bool StudioRegistryString(JsonElement json, string key, string expected) =>
        json.ValueKind == JsonValueKind.Object
        && json.TryGetProperty(key, out var value)
        && value.ValueKind == JsonValueKind.String
        && string.Equals(value.GetString(), expected, StringComparison.Ordinal);

    private static bool StudioRegistryStringIn(JsonElement json, string key, string first, string second) =>
        StudioRegistryString(json, key, first) || StudioRegistryString(json, key, second);

    private static bool StudioRegistryBool(JsonElement json, string key, bool expected) =>
        json.ValueKind == JsonValueKind.Object
        && json.TryGetProperty(key, out var value)
        && value.ValueKind == (expected ? JsonValueKind.True : JsonValueKind.False);

    private static bool StudioRegistryLong(JsonElement json, string key, long expected) =>
        json.ValueKind == JsonValueKind.Object
        && json.TryGetProperty(key, out var value)
        && value.ValueKind == JsonValueKind.Number
        && value.TryGetInt64(out var actual) && actual == expected;

    private static string? StudioRegistryReadString(JsonElement json, string key) =>
        json.ValueKind == JsonValueKind.Object
        && json.TryGetProperty(key, out var value)
        && value.ValueKind == JsonValueKind.String
            ? value.GetString() : null;
}
