"""Windows 2.3 post-install VERIFY cannot bypass the new SSH/HTTPS Bearer policy."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "windows/desktop/release/Verify-Phase2Prebuilt.ps1"
PREVIEW_CI = ROOT / ".github/workflows/p0-three-shot-developer-preview.yml"


def test_verifier_guard_rejects_legacy_lan_before_starting_any_executable() -> None:
    """历史 settings.json 的明文 LAN URL 不能触发 GUI/诊断启动。"""

    source = VERIFY.read_text(encoding="utf-8-sig")
    function = source.index("function Assert-SecureCoreAddress")
    saved = source.index("$baseUrl = Assert-SecureCoreAddress -Url ([string]$settings.macBaseUrl)")
    final_gate = source.index("$baseUrl = Assert-SecureCoreAddress -Url $baseUrl")
    launch = source.index('Start-Process -FilePath $executable -WorkingDirectory')
    diagnostics = source.index('Start-Process -FilePath $diagnostic -ArgumentList')

    # 设备令牌可能被诊断进程读取；先校验 URL 再允许任何可执行程序运行。
    assert function < saved < final_gate < launch < diagnostics
    assert '$baseUrl      = "http://127.0.0.1:18766"' in source
    assert '$baseUrl      = "http://127.0.0.1:8766"' not in source
    assert 'Get-Content -LiteralPath $settingsPath' not in source or (
        "Assert-SecureCoreAddress" in source
    )


def test_verifier_policy_covers_credential_injection_and_path_smuggling() -> None:
    """不能通过 URI 用户信息、路径、查询或片段绕过校验。"""

    source = VERIFY.read_text(encoding="utf-8-sig")
    for required in (
        '[Uri]::TryCreate($Url, [UriKind]::Absolute, [ref]$uri)',
        '$uri.UserInfo',
        '$uri.Query',
        '$uri.Fragment',
        '$uri.AbsolutePath -ne "/"',
        '$uri.IsLoopback',
        '$uri.Scheme -eq "https"',
        "SECURE_CORE_VERIFIER_ADDRESS_POLICY=PASS",
        "NO_NETWORK=TRUE; NO_GUI=TRUE",
        "http://192.168.1.161:8766/",
        "https://name:password@mac.example.test/",
    ):
        assert required in source


def test_native_windows_ci_executes_ps51_verifier_policy_without_network() -> None:
    """不依赖人工运行安装器或 SSH，原生 PowerShell 5.1 验证直接拒绝危险地址。"""

    workflow = PREVIEW_CI.read_text(encoding="utf-8")
    assert "Verify-Phase2Prebuilt.ps1" in workflow
    assert "-AddressPolicySelfTest" in workflow
    assert "P0_SECURE_VERIFIER_NATIVE_SELFTEST_FAILED" in workflow
