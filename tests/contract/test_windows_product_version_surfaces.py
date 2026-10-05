"""Windows WPF public identity and internal build-version resource contract."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
SMOKE = (
    ROOT
    / "windows"
    / "desktop"
    / "tests"
    / "PicotooPet.Desktop.Core.SmokeTests"
)
PRODUCT_VERSION_FILE = ROOT / "src" / "picotoopet_core" / "product-version.txt"
RELEASE_INVARIANTS = ROOT / "contracts" / "release" / "project-goal-invariants.json"


def read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


def test_canonical_product_version_is_2_3_27_1() -> None:
    """四段式工程版本继续用于安装、兼容和诊断，不等同于公共产品名。"""

    assert PRODUCT_VERSION_FILE.read_text(encoding="utf-8").strip() == "2.3.27.1"
    release = json.loads(RELEASE_INVARIANTS.read_text(encoding="utf-8"))
    assert release["windows"]["product_version"]["value"] == "2.3.27.1"


def test_shell_binds_superpower_public_identity_without_engineering_version() -> None:
    """主窗口正常视图只显示 Superpower v1.0，工程版本留在诊断面。"""

    shell = read(DESKTOP, "Views/ShellWindow.xaml")
    view_model = read(DESKTOP, "ViewModels/ShellViewModel.cs")
    provider = read(DESKTOP, "Versioning/ProductVersionInfo.cs")

    assert 'Title="{Binding WindowTitle, Mode=OneWay}"' in shell
    assert 'Text="{Binding ControlCenterSubtitle, Mode=OneWay}"' in shell
    assert "Control Center · Slice B" not in shell
    assert "ProductVersionInfo.WindowTitle" in view_model
    assert "ProductVersionInfo.ControlCenterSubtitle" in view_model
    assert 'ProductName = "PicotooPet AI"' in provider
    assert 'SuperpowerLabel = "Superpower v1.0"' in provider
    assert 'WindowTitle => $"{ProductName} — {SuperpowerLabel}"' in provider
    assert 'ControlCenterSubtitle => $"{SuperpowerLabel} · Control Center"' in provider
    assert 'WindowTitle => $"{ProductName} — {SuperpowerLabel} · {Current}"' not in provider
    assert 'ControlCenterSubtitle => $"{SuperpowerLabel} · Control Center · v{Current}"' not in provider


def test_desktop_and_smoke_outputs_receive_the_canonical_version_file() -> None:
    desktop_project = read(DESKTOP, "PicotooPet.Desktop.csproj")
    smoke_project = read(SMOKE, "PicotooPet.Desktop.Core.SmokeTests.csproj")

    for project in (desktop_project, smoke_project):
        assert "src\\picotoopet_core\\product-version.txt" in project
        assert 'Link="product-version.txt"' in project
        assert "<CopyToOutputDirectory>PreserveNewest</CopyToOutputDirectory>" in project
    assert "<CopyToPublishDirectory>Always</CopyToPublishDirectory>" in desktop_project


def test_real_sta_smoke_runs_public_identity_binding_and_internal_version_check() -> None:
    program = read(SMOKE, "Program.cs")
    smoke = read(SMOKE, "ProductVersionWpfSmokeTests.cs")

    assert "ProductVersionWpfSmokeTests.Run();" in program
    for required in (
        "ShellViewModel.CreateForSmokeTest",
        "BindingMode.OneWay",
        "Measure(new Size(900, 700))",
        "Arrange(new Rect(0, 0, 900, 700))",
        "UpdateLayout()",
        "DispatcherPriority.DataBind",
        'ProductVersionInfo.Current == "2.3.27.1"',
        '"PicotooPet AI — Superpower v1.0"',
        '"Superpower v1.0 · Control Center"',
    ):
        assert required in smoke
    assert '"PicotooPet AI — Superpower v1.0 · 2.3.27.1"' not in smoke
    assert '"Superpower v1.0 · Control Center · v2.3.27.1"' not in smoke


def test_published_self_test_reports_public_identity_and_internal_version_separately() -> None:
    self_test = read(DESKTOP, "Services/AppSelfTest.cs")
    for required in (
        '["product_version"]',
        '["window_title"]',
        '["control_center_subtitle"]',
        "ProductVersionInfo.Current",
        "ProductVersionInfo.WindowTitle",
        "ProductVersionInfo.ControlCenterSubtitle",
    ):
        assert required in self_test


def test_published_self_test_tracks_business_automation_navigation() -> None:
    self_test = read(DESKTOP, "Services/AppSelfTest.cs")

    # Navigation gate: current simple mode exposes six operator entries by default.
    # Business Automation remains reachable from Advanced Home.
    assert "shell.NavigationItems.Count != 6" in self_test
    assert "NavigationRoute.AdvancedHome" in self_test
    assert "NavigationRoute.BusinessAutomation" in self_test
