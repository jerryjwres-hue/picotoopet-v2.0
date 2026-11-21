"""#296: the real 2.3 Windows package transports the existing device session over SSH."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "windows/desktop/release"
BUILDER = ROOT / "windows/desktop/scripts/Build-Phase2WindowsRelease.ps1"
APP = ROOT / "windows/desktop/src/PicotooPet.Desktop"


def test_ssh_helper_has_no_auto_trust_no_password_and_loopback_only() -> None:
    """安全隧道只承载 2.3 API；不传递 Owner、Worker 密钥或 GPU 凭据。"""

    ps = (RELEASE / "Start-SecureMacTunnel.ps1").read_text(encoding="utf-8-sig")
    vbs = (RELEASE / "CONNECT_MAC_SECURE.vbs").read_text(encoding="utf-8")
    for required in (
        "StrictHostKeyChecking=yes",
        "BatchMode=yes",
        "PasswordAuthentication=no",
        "ExitOnForwardFailure=yes",
        "127.0.0.1:18766:127.0.0.1:",
        "System32\\OpenSSH\\ssh.exe",
        "SECURE_MAC_TUNNEL=READY",
        "SECURE_MAC_TUNNEL_SELFTEST=PASS_NO_NETWORK_NO_GPU",
    ):
        assert required in ps
    assert "CONNECT_MAC_SECURE" not in ps
    assert "Start-SecureMacTunnel.ps1" in vbs
    assert "PICOTOO_WORKER_ATTEST_KEY" not in ps
    assert "Authorization:" not in ps
    assert "Bearer " not in ps
    assert "sshpass" not in ps


def test_studio_enforces_secure_address_before_token_and_defaults_loopback() -> None:
    """已有持久化 LAN 地址也不能在自动连接期间发送设备 Bearer。"""

    vm = (APP / "ViewModels/MainWindowViewModel.cs").read_text(encoding="utf-8")
    settings = (APP / "Services/DesktopSettingsStore.cs").read_text(encoding="utf-8")
    policy = (APP / "Services/SecureCoreEndpoint.cs").read_text(encoding="utf-8")
    smoke = (
        ROOT / "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/"
        "SecureCoreEndpointSmokeTests.cs"
    ).read_text(encoding="utf-8")
    assert "http://127.0.0.1:18766" in settings
    assert "http://192.168.1.161:8766" not in settings
    assert vm.index("SecureCoreEndpoint.IsAllowed(baseUri)") < vm.index(
        "await CancelConnectionAsync()"
    )
    assert "return uri.IsLoopback" in policy
    assert "Uri.UriSchemeHttps" in policy
    assert "http://192.168.1.161:8766/" in smoke


def test_windows_prebuilt_zip_and_installed_payload_include_tunnel() -> None:
    """发布前的 PS5.1 自测与 payload 哈希覆盖为安装后重复启动提供依据。"""

    builder = BUILDER.read_text(encoding="utf-8-sig")
    assert 'Join-Path $payloadRoot "tools\\connection"' in builder
    assert builder.index('Join-Path $payloadRoot "tools\\connection"') < builder.index(
        "$files = @("
    )
    assert '"CONNECT_MAC_SECURE.vbs"' in builder
    assert '"Start-SecureMacTunnel.ps1"' in builder
    assert "SECURE_MAC_TUNNEL_SELFTEST=PASS_NO_NETWORK_NO_GPU" in builder


def test_install_and_rollback_keep_tunnel_shortcut_bound_to_active_version() -> None:
    """新版本成功、安装失败与回滚成功都必须维护同一个连接快捷方式。"""

    common = (RELEASE / "Phase2Prebuilt.Common.ps1").read_text(encoding="utf-8-sig")
    install = (RELEASE / "Install-Phase2Prebuilt.ps1").read_text(encoding="utf-8-sig")
    rollback = (RELEASE / "Rollback-Phase2Prebuilt.ps1").read_text(encoding="utf-8-sig")
    assert "function Set-PicotooTunnelShortcut" in common
    assert "Picotoo Pet 安全连接.lnk" in common
    assert 'Join-Path $env:WINDIR "System32\\wscript.exe"' in common
    assert "Set-PicotooTunnelShortcut -VersionRoot $finalPath" in install
    assert "Set-PicotooTunnelShortcut -VersionRoot ([string]$previousCurrent.path)" in install
    assert 'Set-PicotooTunnelShortcut -VersionRoot ""' in install
    assert "Set-PicotooTunnelShortcut -VersionRoot ([string]$previous.path)" in rollback
    assert "Set-PicotooTunnelShortcut -VersionRoot ([string]$current.path)" in rollback


def test_verifier_refuses_legacy_lan_url_before_device_diagnostics() -> None:
    """诊断程序与 Studio 使用同一拒绝局域网明文的策略。"""

    verify = (RELEASE / "Verify-Phase2Prebuilt.ps1").read_text(encoding="utf-8-sig")
    assert 'function Assert-SecureCoreAddress' in verify
    assert '$baseUrl      = "http://127.0.0.1:18766"' in verify
    assert verify.index('$baseUrl = Assert-SecureCoreAddress -Url $baseUrl') < verify.index(
        "Start-Process -FilePath $diagnostic"
    )
    assert "$uri.Scheme -eq 'http' -and $uri.IsLoopback" in verify
    assert "$uri.Scheme -eq 'https'" in verify
