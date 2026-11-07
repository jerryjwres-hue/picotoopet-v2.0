using System.Net;

namespace PicotooPet.Desktop.Core.OwnerReview;

/// <summary>主人审核请求允许的传输模式。</summary>
public enum OwnerReviewTransportMode
{
    /// <summary>仅由注入的 HttpMessageHandler 响应，永不触网（单元/UI 测试）。</summary>
    Mock,

    /// <summary>仅限本机 http 回环地址（开发者本机 Core）。</summary>
    LoopbackOnly,

    /// <summary>经验收的 Windows→Mac 加密传输；当前未验收，被硬阻断。</summary>
    VerifiedEncrypted,
}

/// <summary>集中的传输安全闸门：未验收的加密传输一律失败关闭。</summary>
public static class OwnerReviewTransportGate
{
    /// <summary>真实 Windows→Mac 加密/认证传输尚未验收；该常量只能由后续独立 PR 在验收后修改。</summary>
    public const bool EncryptedMacTransportAccepted = false;

    public const string StatusLabel = "TRANSPORT_SECURITY=BLOCKED";

    /// <summary>校验基地址与模式；不满足时抛出 TransportBlocked。</summary>
    public static void Require(OwnerReviewTransportMode mode, Uri baseAddress)
    {
        ArgumentNullException.ThrowIfNull(baseAddress);
        if (!baseAddress.IsAbsoluteUri || !string.IsNullOrEmpty(baseAddress.UserInfo))
        {
            throw Blocked();
        }
        switch (mode)
        {
            case OwnerReviewTransportMode.Mock:
                // 保留域名 .invalid 永远无法解析；防止测试模式被误用于真实主机。
                if (!baseAddress.Host.EndsWith(".invalid", StringComparison.OrdinalIgnoreCase))
                {
                    throw Blocked();
                }
                return;
            case OwnerReviewTransportMode.LoopbackOnly:
                if (baseAddress.Scheme != Uri.UriSchemeHttp
                    && baseAddress.Scheme != Uri.UriSchemeHttps)
                {
                    throw Blocked();
                }
                if (!IsLoopback(baseAddress))
                {
                    throw Blocked();
                }
                return;
            case OwnerReviewTransportMode.VerifiedEncrypted:
                if (!EncryptedMacTransportAccepted || baseAddress.Scheme != Uri.UriSchemeHttps)
                {
                    throw Blocked();
                }
                return;
            default:
                throw Blocked();
        }
    }

    private static bool IsLoopback(Uri address)
    {
        if (string.Equals(address.Host, "localhost", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }
        return IPAddress.TryParse(address.Host.Trim('[', ']'), out var ip) && IPAddress.IsLoopback(ip);
    }

    private static OwnerReviewException Blocked() => new(
        OwnerReviewFailureKind.TransportBlocked,
        0,
        "OWNER_REVIEW_TRANSPORT_BLOCKED");
}
