"""真实 Windows 2.3 WPF：所有设备 Bearer 连接前必须验证安全 Core 地址。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "windows/desktop/src/PicotooPet.Desktop"
SMOKE = ROOT / "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests"


def test_both_real_wpf_connection_entries_guard_before_token_networking() -> None:
    """新 Shell 与旧适配器共享安全地址规则；原始 Core URL 不被降级。"""

    session = (APP / "Services/ControlCenterSession.cs").read_text(encoding="utf-8")
    old_ui = (APP / "ViewModels/MainWindowViewModel.cs").read_text(encoding="utf-8")
    policy = (APP / "Services/SecureCoreEndpoint.cs").read_text(encoding="utf-8")

    # 新会话在 MacCoreClient / WebSocket 构造之前进行拒绝。
    assert "ValidateConnectionInput(macBaseUrl, token, out var baseUri);" in session
    assert session.index("ValidateConnectionInput(macBaseUrl, token, out var baseUri);") < (
        session.index("MacCoreClient.Create(MacCoreClientOptions.CreateDefault(baseUri, token))")
    )
    assert "if (!SecureCoreEndpoint.IsAllowed(baseUri))" in session
    assert "|| !SecureCoreEndpoint.IsAllowed(baseUri)" in old_ui
    assert old_ui.index("!SecureCoreEndpoint.IsAllowed(baseUri)") < old_ui.index(
        "MacCoreClient.Create(MacCoreClientOptions.CreateDefault(baseUri, token))"
    )

    # 拒绝明文 LAN、URL 内凭据、路径、查询和 Fragment；保留受信任的 HTTPS。
    for required in (
        "uri.IsLoopback",
        "Uri.UriSchemeHttps",
        "uri.UserInfo",
        "uri.Query",
        "uri.Fragment",
        'uri.AbsolutePath != "/"',
    ):
        assert required in policy


def test_default_address_and_native_wpf_smoke_keep_guard_visible() -> None:
    """首次启动不得默认向曾经的局域网 IP 发送设备令牌。"""

    settings = (APP / "Services/DesktopSettingsStore.cs").read_text(encoding="utf-8")
    program = (SMOKE / "Program.cs").read_text(encoding="utf-8")
    smoke = (SMOKE / "SecureCoreEndpointSmokeTests.cs").read_text(encoding="utf-8")

    assert 'new("http://127.0.0.1:18766")' in settings
    assert 'new("http://192.168.1.161:8766")' not in settings
    assert program.count("SecureCoreEndpointSmokeTests.Run();") >= 2
    for required in (
        '"http://127.0.0.1:18766/"',
        '"https://mac.example.test:8766/"',
        '"http://192.168.1.161:8766/"',
        '"http://mac.local:8766/"',
        '"https://name:password@mac.example.test/"',
    ):
        assert required in smoke
