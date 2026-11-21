"""The real Windows diagnostics EXE must refuse unsafe Bearer transport independently of VERIFY."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROGRAM = ROOT / "windows/desktop/tools/PicotooPet.Desktop.Diagnostics/Program.cs"
WINDOWS_CI = ROOT / ".github/workflows/windows-control-center-ci.yml"
BUILDER = ROOT / "windows/desktop/scripts/Build-Phase2WindowsRelease.ps1"


def test_direct_diagnostics_cli_checks_before_reading_credential_manager() -> None:
    """不能依赖调用者一定通过安全的 PowerShell VERIFY 脚本启动。"""

    source = PROGRAM.read_text(encoding="utf-8")
    assert source.index("var options = DiagnosticOptions.Parse(args);") < (
        source.index("new CredentialManagerTokenStore().Read()")
    )
    assert source.index("if (!IsSafeMacBaseUri(baseUri))") < (
        source.index("return new DiagnosticOptions(\n            baseUri")
    )
    assert 'GetValueOrDefault("--base-url", "http://127.0.0.1:18766")' in source
    assert 'GetValueOrDefault("--base-url", "http://192.168.1.161:8766")' not in source


def test_diagnostics_url_policy_matches_real_windows_studio() -> None:
    """检查 Scheme、Loopback、用户信息、路径、Query 和 Fragment。"""

    source = PROGRAM.read_text(encoding="utf-8")
    for rule in (
        "uri.IsLoopback",
        "Uri.UriSchemeHttps",
        "uri.UserInfo",
        "uri.Query",
        "uri.Fragment",
        'uri.AbsolutePath != "/"',
        "UNSAFE_MAC_CORE_URL",
        "https://name:password@mac.example.test/",
        "http://192.168.1.161:8766/",
        "UNSAFE_DIAGNOSTICS_CLI_ALLOWED",
    ):
        assert rule in source


def test_native_ci_and_release_builder_execute_credential_free_exe_negatives() -> None:
    """验证真实已编译程序，不向用户机器或 Comfy 发起网络请求。"""

    workflow = WINDOWS_CI.read_text(encoding="utf-8")
    builder = BUILDER.read_text(encoding="utf-8-sig")
    source = PROGRAM.read_text(encoding="utf-8")
    for text in (workflow, builder, source):
        assert "--endpoint-policy-self-test" in text
    assert "P0_NATIVE_DIAGNOSTICS_ENDPOINT_POLICY_FAILED" in workflow
    assert "--no-build" in workflow
    assert "NO_BEARER_READ=TRUE; NO_NETWORK=TRUE" in source
