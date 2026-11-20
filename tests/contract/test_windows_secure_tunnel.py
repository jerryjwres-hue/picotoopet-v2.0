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


def test_ssh_tunnel_never_handles_sensitive_keys_or_gpu:
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
