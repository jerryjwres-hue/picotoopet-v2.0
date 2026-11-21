namespace PicotooPet.Desktop.Services;

/// <summary>唯一允许设备 Bearer 流经的 Mac Core URL 协议范围。</summary>
public static class SecureCoreEndpoint
{
    /// <summary>只允许本机 HTTP（SSH 隧道）或正常证书校验的 HTTPS。</summary>
    public static bool IsAllowed(Uri? uri)
    {
        if (uri is null || !uri.IsAbsoluteUri
            || !string.IsNullOrEmpty(uri.UserInfo)
            || !string.IsNullOrEmpty(uri.Query)
            || !string.IsNullOrEmpty(uri.Fragment)
            || uri.AbsolutePath != "/")
        {
            return false;
        }

        // 只有本机环回可使用 HTTP，不能将设备令牌发送到局域网明文连接。
        if (uri.Scheme == Uri.UriSchemeHttp)
        {
            return uri.IsLoopback;
        }

        // HTTPS 使用系统默认证书校验；不得禁用证书验证或自动降级。
        return uri.Scheme == Uri.UriSchemeHttps;
    }
}
