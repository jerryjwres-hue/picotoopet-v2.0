"""Native OpenSSH tunnel release contract; no SSH, Mac, network or GPU is touched."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_RELEASE = _ROOT / "windows" / "desktop" / "release"
_TUNNEL = _RELEASE / "Start-SecureMacTunnel.ps1"
_BUILD = _ROOT / "windows" / "desktop" / "scripts" / "Build-Phase2WindowsRelease.ps1"
_STUDIO = _ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
_BOOTSTRAP = _RELEASE / "CONNECT_MAC_SECURE.vbs"


def test_ssh_tunnel_requires_pinned_host_key_and_no_password_or_lan_listener():
    code = _TUNNEL.read_text(encoding="utf-8")
    assert "StrictHostKeyChecking=yes" in code
    assert "ExitOnForwardFailure=yes" in code
    assert "PasswordAuthentication=no" in code
    assert "BatchMode=yes" in code
    assert "127.0.0.1:18766:127.0.0.1:" in code
    assert "IPAddress]::Loopback" in code
    assert "127.0.0.1:18766/api/v1/health" in code
    assert "System32\\OpenSSH\\ssh.exe" in code
    assert "-SelfTest" not in code or "if ($SelfTest)" in code
    assert "StrictHostKeyChecking=accept-new" not in code
    assert "StrictHostKeyChecking=no" not in code or code.count("StrictHostKeyChecking=no") == 1


def test_ssh_tunnel_never_handles_sensitive_keys_or_gpu():
    code = _TUNNEL.read_text(encoding="utf-8")
    for forbidden in (
        "PICOTOO_EXECUTOR_TOKEN", "PICOTOO_WORKER_ATTEST_KEY", "Authorization:",
        "Bearer ", "production-admission/commit", "PICOTOO_SCOPED_GPU_ADMISSION=1",
        "ComfyUI", "sshpass", "curl.exe",
    ):
        assert forbidden not in code
    assert "mac_user" in code and "mac_port" in code and "mac_host" in code
    assert "secure-mac-tunnel.json" in code
    assert "Get-Content" in code
    assert "WriteAllText" in code


def test_installer_bundles_reusable_double_click_bootstrap_and_native_selftest():
    text = _BUILD.read_text(encoding="utf-8")
    assert '"CONNECT_MAC_SECURE.vbs"' in text
    assert '"Start-SecureMacTunnel.ps1"' in text
    assert '"-SelfTest"' in text
    assert "SECURE_MAC_TUNNEL_SELFTEST=PASS_NO_NETWORK_NO_GPU" in text
    bootstrap = _BOOTSTRAP.read_text(encoding="utf-8")
    assert "Start-SecureMacTunnel.ps1" in bootstrap
    assert "-ExecutionPolicy Bypass" in bootstrap
    assert "Option Explicit" in bootstrap


def test_studio_refuses_remote_plaintext_and_defaults_to_loopback():
    main = (_STUDIO / "ViewModels" / "MainWindowViewModel.cs").read_text(encoding="utf-8")
    settings = (_STUDIO / "Services" / "DesktopSettingsStore.cs").read_text(encoding="utf-8")
    assert "WorkerProcessManager.IsSecureCoreAddress(MacBaseUrl)" in main
    assert main.index("IsSecureCoreAddress(MacBaseUrl)") < main.index("await CancelConnectionAsync()")
    assert 'new("http://127.0.0.1:18766")' in settings
    assert "http://192.168.1.161:8766" not in settings


def test_installed_tunnel_is_in_verified_payload_and_fixed_start_menu():
    # 发布构建必须在收集 manifest.files 之前复制连接入口；不能只留 ZIP 临时文件。
    builder = _BUILD.read_text(encoding="utf-8-sig")
    assert 'Join-Path $payloadRoot "tools\\connection"' in builder
    assert builder.index('Join-Path $payloadRoot "tools\\connection"') < builder.index("$files = @(")
    assert '"CONNECT_MAC_SECURE.vbs", "Start-SecureMacTunnel.ps1"' in builder
    installer = (_RELEASE / "Install-Phase2Prebuilt.ps1").read_text(encoding="utf-8-sig")
    rollback = (_RELEASE / "Rollback-Phase2Prebuilt.ps1").read_text(encoding="utf-8-sig")
    for source in (installer, rollback):
        assert "function Set-PicotooTunnelShortcut" in source
        assert "Picotoo Pet 安全连接.lnk" in source
        assert 'Join-Path $env:WINDIR "System32\\wscript.exe"' in source
        assert 'CONNECT_MAC_SECURE.vbs' in source
        assert 'Start-SecureMacTunnel.ps1' in source
    assert "Set-PicotooTunnelShortcut -VersionRoot $finalPath" in installer
    assert "Set-PicotooTunnelShortcut -VersionRoot ([string]$previousCurrent.path)" in installer
    assert "Set-PicotooTunnelShortcut -VersionRoot ([string]$previous.path)" in rollback
    assert "Set-PicotooTunnelShortcut -VersionRoot ([string]$current.path)" in rollback


def test_verifier_uses_secured_port_and_rejects_legacy_plaintext():
    # 真实安装验证程序不能绕过 Studio 安全规则把令牌发到旧 IP:8766。
    script = (_RELEASE / "Verify-Phase2Prebuilt.ps1").read_text(encoding="utf-8-sig")
    assert '$baseUrl      = "http://127.0.0.1:18766"' in script
    assert "function Assert-SecureCoreAddress" in script
    assert "$baseUrl = Assert-SecureCoreAddress -Url $baseUrl" in script
    assert script.index("$baseUrl = Assert-SecureCoreAddress -Url $baseUrl") < script.index("Start-Process -FilePath $diagnostic")
    assert "$uri.Scheme -eq 'http' -and $uri.IsLoopback" in script
    assert "$uri.Scheme -ne 'https'" in script
    assert "不安全 Mac Core 地址" in script


def test_native_release_gate_checks_both_installed_tunnel_files():
    # 自检验证 ZIP payload 本身和原生 PS5.1，而不假设用户保留解压目录。
    gate = (_ROOT / "windows" / "desktop" / "scripts" / "Test-Phase2WindowsRelease.ps1").read_text(encoding="utf-8-sig")
    assert 'Join-Path $payloadRoot "tools\\connection"' in gate
    assert "Assert-ManifestFiles" in gate
    assert "Assert-PowerShellSyntax -Path $tunnelPs" in gate
    assert '"-File", $tunnelPs, "-SelfTest"' in gate
    assert "$tunnelBytes" in gate
