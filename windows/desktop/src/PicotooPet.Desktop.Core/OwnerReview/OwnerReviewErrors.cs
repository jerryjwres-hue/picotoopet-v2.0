using System.Text.Json;

namespace PicotooPet.Desktop.Core.OwnerReview;

/// <summary>主人审核 HTTP 失败的稳定分类。</summary>
public enum OwnerReviewFailureKind
{
    TransportBlocked,
    CredentialMissing,
    Unauthorized,
    Forbidden,
    NotFound,
    Conflict,
    Validation,
    Unavailable,
    Other,
}

/// <summary>主人审核客户端异常；只带 Core 错误码，不带令牌、请求体或证据正文。</summary>
public sealed class OwnerReviewException : Exception
{
    public OwnerReviewException(OwnerReviewFailureKind kind, int statusCode, string code)
        : base("Owner review request failed: " + code)
    {
        Kind = kind;
        StatusCode = statusCode;
        Code = code;
    }

    public OwnerReviewFailureKind Kind { get; }
    public int StatusCode { get; }
    public string Code { get; }

    /// <summary>409 表示提案、来源或预览已过期：只能重新加载，禁止强制覆盖。</summary>
    public bool RequiresReload => Kind == OwnerReviewFailureKind.Conflict;

    /// <summary>面向主人的中文提示。</summary>
    public string ChineseMessage => Code switch
    {
        "OWNER_REVIEW_TRANSPORT_BLOCKED" => "加密传输尚未验收，已阻止向 Mac 发送主人审核请求。",
        "OWNER_REVIEW_CREDENTIAL_MISSING" => "尚未配置主人审核凭据，请先保存专用凭据。",
        "OWNER_REVIEW_ENCRYPTED_TRANSPORT_REQUIRED" => "Core 拒绝：主人审核需要经过核实的本机连接或加密传输。",
        "OWNER_REVIEW_PROPOSAL_STALE" => "提案已过期，请重新加载提案后再审核。",
        "OWNER_REVIEW_SOURCE_STALE" => "来源证据已变化，请重新加载提案后再审核。",
        "OWNER_REVIEW_PREVIEW_MISMATCH" => "预览与当前决定不一致，请重新预览。",
        "OWNER_REVIEW_IDEMPOTENCY_CONFLICT" => "同一幂等键对应了不同内容，请重新预览后再提交。",
        "OWNER_REVIEW_IDEMPOTENCY_KEY_INVALID" => "幂等键无效，请重新预览后再提交。",
        "OWNER_REVIEW_EVIDENCE_BINDING_INVALID" => "字段与来源证据绑定不成立，请重新加载提案。",
        "OWNER_REVIEW_GOAL_SOURCE_NOT_FOUND" => "找不到该 Goal 的来源资料。",
        "OWNER_REVIEW_GOAL_SOURCE_INVALID" => "该 Goal 的来源资料无效。",
        "OWNER_REVIEW_SOURCE_EVIDENCE_MISSING" => "缺少来源证据，需要人工补充，系统不会使用默认值。",
        _ => Kind switch
        {
            OwnerReviewFailureKind.Unauthorized => "主人审核凭据无效或已被撤销（401）。",
            OwnerReviewFailureKind.Forbidden => "该凭据没有此宠物主体的审核权限（403）。",
            OwnerReviewFailureKind.Conflict => "审核数据已过期或冲突（409），请重新加载。",
            OwnerReviewFailureKind.Validation => "提交内容未通过 Core 校验（422）。",
            OwnerReviewFailureKind.NotFound => "未找到该 Goal（404）。",
            OwnerReviewFailureKind.Unavailable => "Core 暂时不可用，请稍后重试。",
            _ => "主人审核请求失败。",
        },
    };

    internal static OwnerReviewException FromResponse(int status, string? body)
    {
        var code = "OWNER_REVIEW_HTTP_" + status;
        if (!string.IsNullOrEmpty(body) && body.Length <= 16384)
        {
            try
            {
                using var doc = JsonDocument.Parse(body);
                if (doc.RootElement.ValueKind == JsonValueKind.Object
                    && doc.RootElement.TryGetProperty("error", out var error)
                    && error.ValueKind == JsonValueKind.Object
                    && error.TryGetProperty("code", out var c)
                    && c.ValueKind == JsonValueKind.String
                    && c.GetString() is { Length: > 0 and <= 80 } parsed)
                {
                    code = parsed;
                }
            }
            catch (JsonException)
            {
                // 保留由状态码推出的错误码；绝不回显格式错误的响应体。
            }
        }
        var kind = status switch
        {
            401 => OwnerReviewFailureKind.Unauthorized,
            403 => OwnerReviewFailureKind.Forbidden,
            404 => OwnerReviewFailureKind.NotFound,
            409 => OwnerReviewFailureKind.Conflict,
            422 => OwnerReviewFailureKind.Validation,
            >= 500 => OwnerReviewFailureKind.Unavailable,
            _ => OwnerReviewFailureKind.Other,
        };
        return new OwnerReviewException(kind, status, code);
    }
}
