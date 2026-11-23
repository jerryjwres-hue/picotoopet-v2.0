using System.Text.Json;
using System.Text.RegularExpressions;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>现有配对 Core 通道的素材证据与 Scoped Goal 入口，不承担正式 OwnerPrincipal 审批。</summary>
public sealed partial class MacCoreClient
{
    private static bool IsScopeDigest(string? value) =>
        value is not null && Regex.IsMatch(value, "^[0-9a-f]{64}$");

    private static void RequireScope(string projectId, string characterRef, string subjectKey, string sha)
    {
        if (!Regex.IsMatch(projectId, "^[A-Za-z0-9_-]{1,100}$")
            || !Regex.IsMatch(characterRef, "^asset-[0-9a-f]{64}$")
            || !Regex.IsMatch(subjectKey, "^pet:[a-z0-9][a-z0-9-]{1,63}$")
            || !IsScopeDigest(sha))
        {
            throw new ArgumentException("无效的素材与宠物证据范围。");
        }
    }

    // 01. 严格按项目、角色资产及宠物键读取本地已审阅声明；不读取文件路径。
    public async Task<JsonElement> GetScopedOwnerPacketsAsync(
        string projectId, string characterRef, string subjectKey, string characterSha,
        CancellationToken cancellationToken = default)
    {
        RequireScope(projectId, characterRef, subjectKey, characterSha);
        var path = "api/v1/studio/owner-subject-packets"
            + "?project_id=" + Uri.EscapeDataString(projectId)
            + "&character_ref=" + Uri.EscapeDataString(characterRef)
            + "&subject_key=" + Uri.EscapeDataString(subjectKey);
        var response = await SendAsync<JsonElement>(
            HttpMethod.Get, path, null, "studio.owner-packets.readonly", null,
            cancellationToken, 128 * 1024).ConfigureAwait(false);
        if (response.ValueKind != JsonValueKind.Object
            || !AssetStringIs(response, "contract", "picotoo.storypack.reviewed-owner-packets.v1")
            || !AssetStringIs(response, "project_id", projectId)
            || !AssetStringIs(response, "character_ref", characterRef)
            || !AssetStringIs(response, "subject_key", subjectKey)
            || !AssetStringIs(response, "character_sha256", characterSha)
            || !AssetBoolIs(response, "owner_approved", false)
            || !AssetBoolIs(response, "production_approval_granted", false)
            || !AssetBoolIs(response, "can_queue", false)
            || !response.TryGetProperty("packets", out var packets)
            || packets.ValueKind != JsonValueKind.Array || packets.GetArrayLength() > 10)
        {
            throw new InvalidOperationException("证据列表回执未通过核验。");
        }
        foreach (var packet in packets.EnumerateArray())
        {
            if (!packet.TryGetProperty("packet_digest", out var digest)
                || digest.ValueKind != JsonValueKind.String || !IsScopeDigest(digest.GetString())
                || !packet.TryGetProperty("claims", out var claims) || !ValidClaims(claims))
            {
                throw new InvalidOperationException("已登记声明内容未通过核验。");
            }
        }
        return response;
    }

    // 02. 新声明只提交用户填写的事实和意图。图像字节登记不等于身份/版权审核。
    public async Task<string> PreviewOwnerPacketAsync(
        JsonElement packet, CancellationToken cancellationToken = default)
    {
        var subjectKey = ValidateOwnerPacket(packet);
        var response = await SendAsync<JsonElement>(
            HttpMethod.Post, "api/v1/autonomous/owner-subject-evidence/preview", packet,
            "studio.owner-packet.preview", null, cancellationToken, 16 * 1024).ConfigureAwait(false);
        if (!AssetStringIs(response, "subject_key", subjectKey)
            || !AssetBoolIs(response, "photo_bytes_verified", false)
            || !AssetBoolIs(response, "owner_confirmation_required", true)
            || !response.TryGetProperty("claim_count", out var count)
            || !count.TryGetInt32(out var n) || n != packet.GetProperty("claims").GetArrayLength()
            || !response.TryGetProperty("packet_digest", out var digest)
            || digest.ValueKind != JsonValueKind.String || !IsScopeDigest(digest.GetString()))
        {
            throw new InvalidOperationException("声明预览回执未通过核验。");
        }
        return digest.GetString()!;
    }

    public async Task CommitReviewedOwnerPacketAsync(
        JsonElement packet, string reviewedDigest, CancellationToken cancellationToken = default)
    {
        var subjectKey = ValidateOwnerPacket(packet);
        if (!IsScopeDigest(reviewedDigest))
        {
            throw new ArgumentException("无效的声明审核摘要。");
        }
        // 仅供用户对确切内容明确确认后的 UI 路径调用。
        var body = JsonSerializer.SerializeToElement(new
        {
            packet, reviewed_digest = reviewedDigest, owner_confirmed = true,
        });
        var response = await SendAsync<JsonElement>(
            HttpMethod.Post, "api/v1/autonomous/owner-subject-evidence/commit", body,
            "studio.owner-packet.commit", null, cancellationToken, 16 * 1024).ConfigureAwait(false);
        if (!AssetStringIs(response, "subject_key", subjectKey)
            || !AssetStringIs(response, "packet_digest", reviewedDigest)
            || !AssetBoolIs(response, "photo_bytes_verified", false)
            || !AssetBoolIs(response, "production_approval_granted", false)
            || !AssetBoolIs(response, "goal_created", false)
            || !response.TryGetProperty("claim_count", out var count)
            || !count.TryGetInt32(out var n) || n != packet.GetProperty("claims").GetArrayLength()
            || !response.TryGetProperty("evidence_ids", out var evidence)
            || evidence.ValueKind != JsonValueKind.Array || evidence.GetArrayLength() != n)
        {
            throw new InvalidOperationException("声明登记回执未通过核验。");
        }
    }

    // 03. 对冻结剧本与证据范围创建现有 Goal；拒绝任何错误范围或未绑定的回执。
    public async Task<string> SubmitScopedStoryGoalAsync(
        JsonElement storyPack, string projectId, string characterRef, string characterSha,
        string subjectKey, string reviewedPacketDigest, string subjectDigest,
        string storyPackDigest, string motionDigest,
        CancellationToken cancellationToken = default)
    {
        RequireScope(projectId, characterRef, subjectKey, characterSha);
        if (!IsScopeDigest(reviewedPacketDigest) || !IsScopeDigest(subjectDigest)
            || !IsScopeDigest(storyPackDigest) || !IsScopeDigest(motionDigest)
            || !AssetStringIs(storyPack, "character_ref", characterRef)
            || !storyPack.TryGetProperty("dynamic_motion", out var motion)
            || !AssetStringIs(motion, "policy", "dynamic-pet-feeding-v1.0.0"))
        {
            throw new ArgumentException("无效的动态剧本审核范围。");
        }
        var body = JsonSerializer.SerializeToElement(new
        {
            storypack = storyPack,
            project_id = projectId,
            owner_subject_key = subjectKey,
            reviewed_packet_sha256 = reviewedPacketDigest,
            confirmed_subject_sha256 = subjectDigest,
        });
        if (JsonSerializer.SerializeToUtf8Bytes(body, JsonOptions).Length > MaxStoryPackRequestBytes)
        {
            throw new ArgumentException("绑定后的剧本超过 128 KiB。");
        }
        var response = await SendAsync<JsonElement>(
            HttpMethod.Post, "api/v1/studio/storypacks/scoped-goal", body,
            "studio.storypack.scoped-goal", null, cancellationToken, MaxStudioPreviewResponseBytes,
            request => request.Headers.Add("X-Picotoo-Goal-Confirmed", "yes")).ConfigureAwait(false);
        if (response.ValueKind != JsonValueKind.Object
            || !AssetStringIs(response, "intent_type", "video.creative")
            || !response.TryGetProperty("goal_id", out var id) || id.ValueKind != JsonValueKind.String
            || string.IsNullOrWhiteSpace(id.GetString())
            || !response.TryGetProperty("workflow_id", out var workflow)
            || workflow.ValueKind != JsonValueKind.String || string.IsNullOrWhiteSpace(workflow.GetString())
            || !response.TryGetProperty("constraints", out var constraints)
            || !AssetBoolIs(constraints, "local_video_preferred", true)
            || !AssetBoolIs(constraints, "read_only_research", true)
            || !constraints.TryGetProperty("storypack_binding", out var binding)
            || !AssetStringIs(binding, "schema", "picotoo.storypack.scoped-goal-binding.v1")
            || !AssetStringIs(binding, "project_id", projectId)
            || !AssetStringIs(binding, "owner_subject_key", subjectKey)
            || !AssetStringIs(binding, "reviewed_packet_sha256", reviewedPacketDigest)
            || !AssetStringIs(binding, "subject_sha256", subjectDigest)
            || !AssetStringIs(binding, "storypack_sha256", storyPackDigest)
            || !AssetStringIs(binding, "dynamic_motion_digest", motionDigest)
            || !binding.TryGetProperty("assets", out var assets)
            || !assets.TryGetProperty("character", out var character)
            || !AssetStringIs(character, "artifact_id", characterRef)
            || !AssetStringIs(character, "sha256", characterSha))
        {
            throw new InvalidOperationException("Goal 未获可验证的冻结范围回执；不得进入生产。");
        }
        return id.GetString()!;
    }

    private static string ValidateOwnerPacket(JsonElement packet)
    {
        if (packet.ValueKind != JsonValueKind.Object
            || !packet.TryGetProperty("subject_key", out var subject)
            || subject.ValueKind != JsonValueKind.String
            || !Regex.IsMatch(subject.GetString()!, "^pet:[a-z0-9][a-z0-9-]{1,63}$")
            || !packet.TryGetProperty("photo_sha256_claim", out var hash)
            || hash.ValueKind != JsonValueKind.String || !IsScopeDigest(hash.GetString())
            || !packet.TryGetProperty("claims", out var claims) || !ValidClaims(claims))
        {
            throw new ArgumentException("请填写角色、场景和计划动作三类明确声明（每条10–500字符）。");
        }
        return subject.GetString()!;
    }

    private static bool ValidClaims(JsonElement claims)
    {
        if (claims.ValueKind != JsonValueKind.Array || claims.GetArrayLength() is < 3 or > 10)
        {
            return false;
        }
        var kinds = new HashSet<string>(StringComparer.Ordinal);
        foreach (var claim in claims.EnumerateArray())
        {
            if (claim.ValueKind != JsonValueKind.Object
                || !claim.TryGetProperty("kind", out var kind) || kind.ValueKind != JsonValueKind.String
                || kind.GetString() is not ("visible_identity" or "visible_scene" or "creative_intent")
                || !claim.TryGetProperty("statement", out var statement)
                || statement.ValueKind != JsonValueKind.String
                || statement.GetString() is not { Length: >= 10 and <= 500 } text
                || !string.Equals(text, text.Trim(), StringComparison.Ordinal))
            {
                return false;
            }
            kinds.Add(kind.GetString()!);
        }
        return kinds.Count == 3;
    }
}
