using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text.Json;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>只登记用户明确选择的文件副本，不接受路径、Owner 批准或生产权限。</summary>
public sealed partial class MacCoreClient
{
    public const int MaxStudioAssetBytes = 16 * 1024 * 1024;

    public async Task<string> ImportStudioAssetAsync(
        string projectId, string role, string mediaType, byte[] data,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(data);
        // 01. 固定输入范围；不允许将任意 Header、URL 或 MIME 传入网络层。
        if (string.IsNullOrWhiteSpace(projectId) || projectId.Length > 100
            || projectId.Any(c => !(char.IsAsciiLetterOrDigit(c) || c is '-' or '_'))
            || role is not ("character" or "scene" or "style")
            || !(mediaType is "image/png" or "image/jpeg" or "image/webp"
                 || role == "style" && mediaType is "text/plain" or "application/json")
            || data.Length is <= 0 or > MaxStudioAssetBytes)
        {
            throw new ArgumentException("不符合本地资产登记合同。");
        }

        // 02. 冻结上传字节与 SHA；不包含本地路径或文件名。
        var snapshot = data.ToArray();
        var digest = Convert.ToHexStringLower(SHA256.HashData(snapshot));
        var receipt = await SendAsync<JsonElement>(
            HttpMethod.Post, "api/v1/studio/assets/import", null,
            "studio.asset.import.local", null, cancellationToken, 16 * 1024,
            request =>
            {
                request.Headers.Add("X-Picotoo-Project-Id", projectId);
                request.Headers.Add("X-Picotoo-Asset-Role", role);
                request.Headers.Add("X-Picotoo-Asset-SHA256", digest);
                request.Headers.Add("X-Picotoo-Import-Confirmed", "yes");
                request.Content = new ByteArrayContent(snapshot);
                request.Content.Headers.ContentType = new MediaTypeHeaderValue(mediaType);
            }).ConfigureAwait(false);

        // 03. 仅接受与本次真实上传完全一致且明确未批准的回执。
        if (receipt.ValueKind != JsonValueKind.Object
            || !AssetStringIs(receipt, "contract", "picotoo.storypack.local-asset-intake.v1")
            || !AssetStringIs(receipt, "project_id", projectId)
            || !AssetStringIs(receipt, "role", role)
            || !AssetStringIs(receipt, "sha256", digest)
            || !AssetStringIs(receipt, "media_type", mediaType)
            || !AssetStringIs(receipt, "cloud_policy", "local_only")
            || !AssetStringIs(receipt, "source_provenance", "OPERATOR_SUBMITTED_COPY_UNVERIFIED")
            || !(AssetStringIs(receipt, "registration", "CREATED")
                 || AssetStringIs(receipt, "registration", "REPLAY"))
            || !receipt.TryGetProperty("size_bytes", out var length)
            || length.ValueKind != JsonValueKind.Number
            || !length.TryGetInt32(out var size) || size != snapshot.Length
            || !AssetBoolIs(receipt, "content_integrity_verified", true)
            || new[] { "owner_approved", "master_approved", "is_original", "can_queue",
                       "gpu_post_authorized" }.Any(key => !AssetBoolIs(receipt, key, false))
            || !receipt.TryGetProperty("artifact_id", out var idField)
            || idField.ValueKind != JsonValueKind.String
            || idField.GetString() is not { Length: 70 } assetId
            || !assetId.StartsWith("asset-", StringComparison.Ordinal)
            || assetId.Skip(6).Any(c => !(c is >= '0' and <= '9' or >= 'a' and <= 'f')))
        {
            throw new InvalidOperationException("资产回执未验证；不得绑定剧本或生成任务。");
        }

        return assetId;
    }

    private static bool AssetStringIs(JsonElement value, string key, string expected) =>
        value.TryGetProperty(key, out var field) && field.ValueKind == JsonValueKind.String
        && string.Equals(field.GetString(), expected, StringComparison.Ordinal);

    private static bool AssetBoolIs(JsonElement value, string key, bool expected) =>
        value.TryGetProperty(key, out var field)
        && field.ValueKind == (expected ? JsonValueKind.True : JsonValueKind.False);
}
