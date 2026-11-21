using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>2.3 Windows Studio 安全隧道的设备令牌网络前门禁。</summary>
internal static class SecureCoreEndpointSmokeTests
{
    /// <summary>验证本机 SSH 环回、可信 HTTPS 与全部明文 LAN 拒绝路径。</summary>
    public static void Run()
    {
        SmokeAssert.True(
            DesktopSettings.Default.MacBaseUrl == "http://127.0.0.1:18766",
            "默认 Mac Core 连接必须是 Windows 本机 SSH 隧道地址");

        foreach (var valid in new[]
        {
            "http://127.0.0.1:18766/",
            "http://localhost:18766/",
            "https://mac.example.test:8766/",
        })
        {
            SmokeAssert.True(
                SecureCoreEndpoint.IsAllowed(new Uri(valid)),
                "合法 HTTPS / loopback URL 被误拦：" + valid);
        }

        foreach (var invalid in new[]
        {
            "http://192.168.1.161:8766/",
            "http://mac.local:8766/",
            "http://example.com/",
            "http://127.0.0.1:18766/api/v1/health",
            "http://127.0.0.1:18766/?key=secret",
            "https://name:password@mac.example.test/",
            "https://mac.example.test/#fragment",
            "ftp://127.0.0.1:18766/",
        })
        {
            SmokeAssert.True(
                !SecureCoreEndpoint.IsAllowed(new Uri(invalid)),
                "危险的设备令牌出口被错误允许：" + invalid);
        }
        SmokeAssert.True(!SecureCoreEndpoint.IsAllowed(null), "空 URL 必须安全拒绝");
    }
}
