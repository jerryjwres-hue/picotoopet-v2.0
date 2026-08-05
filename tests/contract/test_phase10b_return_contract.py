from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    """按 UTF-8 读取仓库内固定合同文件。"""

    return (ROOT / relative).read_text(encoding="utf-8")


def test_return_safe_projection_schema_is_strict_and_bounded() -> None:
    """Return API 投影必须拒绝未知字段、任意 changed file 和外部 Provider。"""

    schema = json.loads(
        read("contracts/handoff/v1/schemas/return_preview.schema.json")
    )

    assert schema["additionalProperties"] is False
    assert schema["properties"]["provider"]["const"] == "local-contract-self-test"
    assert schema["properties"]["changed_file_count"]["const"] == 0
    assert schema["properties"]["event_count"]["maximum"] == 16
    assert schema["properties"]["event_summaries"]["maxItems"] == 16
    assert schema["properties"]["execution_notice"]["maxLength"] == 240


def test_return_api_accepts_no_file_path_command_or_manifest_body() -> None:
    """Phase 10B-A REST 写入只能触发服务器自有演练，不能接收任意包。"""

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


def test_return_validator_fails_closed_on_links_paths_secrets_and_claims() -> None:
    """验证器必须保留整体隔离错误码且不执行 Return 中的内容。"""

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
        "contract_validated",
        "quarantined",
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
    """Windows 只能观察安全投影和触发无正文自测，不得提供文件或命令 UI。"""

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
