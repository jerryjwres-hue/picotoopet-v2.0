"""Native WPF Handoff / Return Contract v1 status-page source boundary."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"


def read(relative: str) -> str:
    return (DESKTOP / relative).read_text(encoding="utf-8")


def test_cloud_development_route_uses_native_contract_page() -> None:
    shell = read("ViewModels/ShellViewModel.cs")
    app = read("App.xaml")

    assert "new CloudDevelopmentPageViewModel()" in shell
    assert "CloudDevelopmentPageViewModel" in app
    assert "CloudDevelopmentPage" in app
    assert "Handoff / Return Contract v1 已冻结；Provider 尚未配置。" in shell


def test_cloud_development_page_exposes_frozen_contract_without_provider_actions() -> None:
    view_model = read("ViewModels/CloudDevelopmentPageViewModel.cs")
    page = read("Views/Pages/CloudDevelopmentPage.xaml")
    combined = view_model + "\n" + page

    for required in (
        'ContractVersion => "1.0.0"',
        'ContractStatus => "Approved / Frozen"',
        "ProviderConfigured => false",
        "Mac Handoff Manager",
        "Approval Center",
        "Windows Dev Broker",
        "Provider Adapter",
        "Isolated Worktree / Sandbox",
        "Return Package",
        "Local Validation",
        "Human Review",
        "PR / Merge / Release Approval",
        "Protected 原件",
        "本地验证",
        "自动 push",
        "Phase 10A",
        "Phase 10B",
    ):
        assert required in combined

    for forbidden in (
        "WebView",
        "Electron",
        "http://localhost",
        "Process.Start",
        "System.Diagnostics.Process",
        "Grok Build",
        "Claude Code",
        "OpenFileDialog",
        "CommandBinding",
        "<Button",
    ):
        assert forbidden not in combined
