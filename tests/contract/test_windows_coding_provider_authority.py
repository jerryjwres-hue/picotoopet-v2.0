from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HANDOFF_SESSION = (
    ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop"
    / "Services"
    / "ControlCenterSession.Handoffs.cs"
)
PROVIDER_CLIENT = (
    ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop.Core"
    / "Networking"
    / "MacCoreProviderClient.cs"
)
PROVIDER_SESSION = (
    ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop"
    / "Services"
    / "ControlCenterSession.Provider.cs"
)
PROVIDER_GATEWAY = (
    ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop"
    / "Services"
    / "IProviderSessionGateway.cs"
)
PROVIDER_VIEW_MODEL = (
    ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop"
    / "ViewModels"
    / "ProviderSessionViewModel.cs"
)
PROVIDER_PANEL = (
    ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop"
    / "Views"
    / "Pages"
    / "ProviderSessionPanel.xaml"
)


def test_windows_filters_handoff_templates_to_manual_provider_only() -> None:
    source = HANDOFF_SESSION.read_text(encoding="utf-8-sig")
    compact = "".join(source.split())

    assert "GetHandoffTemplatesAsync" in source
    assert ".Where(" in source
    assert 'template.Provider,"manual",StringComparison.Ordinal' in compact
    assert ".ToArray();" in source


def test_windows_cannot_start_coding_provider_session_directly() -> None:
    client = PROVIDER_CLIENT.read_text(encoding="utf-8-sig")
    session = PROVIDER_SESSION.read_text(encoding="utf-8-sig")
    gateway = PROVIDER_GATEWAY.read_text(encoding="utf-8-sig")
    view_model = PROVIDER_VIEW_MODEL.read_text(encoding="utf-8-sig")
    panel = PROVIDER_PANEL.read_text(encoding="utf-8-sig")

    # Windows may acknowledge account availability and may issue an emergency
    # cancellation, but the Core-owned Frugal arbiter is the only authority
    # allowed to create a Codex/Claude coding Provider Session.
    assert "ConfirmUsageAsync" in client
    assert "ConfirmProviderUsageAsync" in session
    assert "ConfirmUsageAsync" in gateway
    assert "ConfirmUsageCommand" in view_model
    assert "记录人工额度确认" in panel

    assert "CancelSessionAsync" in client
    assert "CancelProviderSessionAsync" in session
    assert "CancelSessionAsync" in gateway
    assert "CancelSessionCommand" in view_model
    assert "取消活动 Session" in panel

    assert "StartSessionAsync" not in client
    assert "provider-sessions/codex" not in client
    assert "StartProviderSessionAsync" not in session
    assert "StartSessionAsync" not in gateway
    assert "StartSessionCommand" not in view_model
    assert "启动一次低预算 Codex Session" not in panel


def test_windows_usage_confirmation_supports_core_selected_dual_providers() -> None:
    view_model = PROVIDER_VIEW_MODEL.read_text(encoding="utf-8-sig")
    panel = PROVIDER_PANEL.read_text(encoding="utf-8-sig")

    # This is not a provider picker. Both values must come only from already
    # approved Handoffs whose provider was persisted by Mac Core.
    assert '"codex"' in view_model
    assert '"claude_code"' in view_model
    assert "Core 已绑定" in panel
    assert "Codex / Claude Code" in panel
