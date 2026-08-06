from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    """按 UTF-8 读取仓库内固定合同文件。"""

    return (ROOT / relative).read_text(encoding="utf-8")


def test_return_safe_projection_schema_is_strict_and_provider_bounded() -> None:
    """Return 投影只允许两个内置 Provider 及最多一个固定文本变更。"""

    schema = json.loads(
        read("contracts/handoff/v1/schemas/return_preview.schema.json")
    )

    assert schema["additionalProperties"] is False
    assert schema["properties"]["provider"]["enum"] == [
        "local-contract-self-test",
        "local-mock-dev-broker",
    ]
    assert schema["properties"]["changed_file_count"]["minimum"] == 0
    assert schema["properties"]["changed_file_count"]["maximum"] == 1
    assert schema["properties"]["event_count"]["maximum"] == 16
    assert schema["properties"]["event_summaries"]["maxItems"] == 16
    assert schema["properties"]["execution_notice"]["maxLength"] == 280
    assert len(schema["allOf"]) == 2


def test_phase10b_a_return_api_accepts_no_file_path_command_or_manifest_body() -> None:
    """原有无正文自测接口不能因 Mock Broker 扩展而接收任意包。"""

    route = read("src/picotoopet_core/api/routes/returns.py")

    assert '"/returns"' in route
    assert '"/returns/{return_id}"' in route
    assert '"/handoffs/{handoff_id}/returns/self-test"' in route
    assert "Idempotency-Key" in route
    assert "await request.body()" in route
    for forbidden in (
        "UploadFile",
        "File(",
        "Form(",
        "multipart",
        "base64",
        "path:",
        "command:",
        "manifest:",
    ):
        assert forbidden not in route


def test_zero_change_return_validator_remains_fail_closed() -> None:
    """Phase 10B-A 验证器仍必须保持零变更整体隔离策略。"""

    service = read("src/picotoopet_core/returns/service.py")

    for required in (
        "LINK_ENTRY_DENIED",
        "PATH_POLICY_DENIED",
        "FILE_ALLOWLIST_DENIED",
        "HANDOFF_BINDING_MISMATCH",
        "CHANGED_FILES_DENIED",
        "PROVIDER_CLAIM_DENIED",
        "SECRET_CONTENT_DENIED",
        "EVENT_SEQUENCE_INVALID",
        "EVENT_ID_DUPLICATE",
        "SHA256_COVERAGE_MISMATCH",
        "ReturnStatus.CONTRACT_VALIDATED",
        "ReturnStatus.QUARANTINED",
    ):
        assert required in service
    for forbidden in (
        "subprocess",
        "Popen",
        "os.system",
        "shell=True",
        "git push",
        "git merge",
    ):
        assert forbidden not in service


def test_mock_broker_validator_has_independent_fixed_policy() -> None:
    """Mock Broker 策略必须独立锁定单一变更、四事件和秘密扫描。"""

    service = read("src/picotoopet_core/returns/mock_broker.py")

    for required in (
        '"local-mock-dev-broker"',
        '"changes/docs/mock-provider-proof.txt"',
        '"broker.started"',
        '"broker.sandbox.ready"',
        '"provider.returned"',
        '"broker.return.submitted"',
        '"SECRET_CONTENT_DENIED"',
        '"PROVIDER_CLAIM_DENIED"',
        '"SHA256_COVERAGE_MISMATCH"',
        "changed_file_count=1",
    ):
        assert required in service
    for forbidden in (
        "subprocess",
        "Popen",
        "os.system",
        "shell=True",
        "git push",
        "git merge",
    ):
        assert forbidden not in service


def test_windows_return_client_and_panel_are_bounded_native_wpf() -> None:
    """现有 Return 面板仍只能观察安全投影和触发无正文自测。"""

    client = read(
        "windows/desktop/src/PicotooPet.Desktop.Core/Networking/"
        "MacCoreReturnClient.cs"
    )
    panel = read(
        "windows/desktop/src/PicotooPet.Desktop/Views/Pages/"
        "ReturnValidationPanel.xaml"
    )
    context = read(
        "windows/desktop/src/PicotooPet.Desktop/Views/ReturnGatewayContext.cs"
    )

    assert "ResponseHeadersRead" in client
    assert "MaxReturnResponseBytes = 128 * 1024" in client
    assert "Idempotency-Key" in client
    assert "RunSelfTestAsync" in client
    assert "FrameworkPropertyMetadataOptions.Inherits" in context
    assert "运行本地 Return 合同验证" in panel
    assert "Return 安全预览" in panel
    for forbidden in (
        "PasswordBox",
        "WebBrowser",
        "WebView",
        "TextBox",
        "OpenFileDialog",
        "AllowDrop",
        "DragEnter",
        "Process",
        "PowerShell",
        "cmd.exe",
    ):
        assert forbidden not in panel
