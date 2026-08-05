"""Native WPF Phase 10A Handoff preparation source boundary."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
DESKTOP_CORE = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop.Core"


def read(relative: str) -> str:
    return (DESKTOP / relative).read_text(encoding="utf-8")


def read_core(relative: str) -> str:
    return (DESKTOP_CORE / relative).read_text(encoding="utf-8")


def test_cloud_development_route_uses_live_native_phase10a_page() -> None:
    shell = read("ViewModels/ShellViewModel.cs")
    app = read("App.xaml")

    assert "new ControlCenterHandoffGateway(_session)" in shell
    assert "new CloudDevelopmentPageViewModel()" in shell
    assert "CloudDevelopmentPageViewModel" in app
    assert "CloudDevelopmentPage" in app
    assert "Handoff / Return Contract v1 已冻结；Provider 尚未配置。" in shell
    assert "普通连接快照不得清空页面实例" in shell


def test_cloud_development_page_exposes_only_bounded_phase10a_actions() -> None:
    view_model = read("ViewModels/CloudDevelopmentPageViewModel.cs")
    page = read("Views/Pages/CloudDevelopmentPage.xaml")
    gateway = read("Services/IHandoffGateway.cs")
    client = read_core("Networking/MacCoreHandoffClient.cs")
    combined = "\n".join((view_model, page, gateway, client))

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
        "RefreshCommand",
        "PrepareCommand",
        "SubmitCommand",
        "HandoffPrepareRequest",
        "Idempotency-Key",
        "Provider 未安装、未配置、未调用",
        "MaxHandoffResponseBytes",
    ):
        assert required in combined

    assert page.count("<Button") == 3
    assert page.count("<TextBox") == 2

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
        "PasswordBox",
        "WebBrowser",
        "allowed_write",
        "allowed_read",
        "shell_command",
        "provider_token",
    ):
        assert forbidden not in combined
