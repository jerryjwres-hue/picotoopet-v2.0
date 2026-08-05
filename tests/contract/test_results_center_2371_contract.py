"""Native Results Center contract regression tests retained in 2.3.8.1."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_mac_core_explicitly_declares_safe_result_capabilities() -> None:
    contract = read("src/picotoopet_core/api/contracts/control_center.py")
    assert "result_list: bool = True" in contract
    assert "result_preview: bool = True" in contract


def test_results_center_reuses_bounded_diagnostic_contract() -> None:
    client = read(
        "windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.cs"
    )
    session = read(
        "windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.Tasks.cs"
    )
    view_model = read(
        "windows/desktop/src/PicotooPet.Desktop/ViewModels/ResultsPageViewModel.cs"
    )

    assert "MaxDiagnosticResultBytes = 64 * 1024" in client
    assert "GetDiagnosticResultAsync" in session
    assert "GetDiagnosticResultAsync" in view_model
    assert "system.diagnostic_snapshot" in view_model
    assert "CanPreview" in view_model
    assert "通用 JSON" not in view_model


def test_results_page_is_native_wpf_and_registered_in_shell() -> None:
    app = read("windows/desktop/src/PicotooPet.Desktop/App.xaml")
    shell = read(
        "windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs"
    )
    page = read(
        "windows/desktop/src/PicotooPet.Desktop/Views/Pages/ResultsPage.xaml"
    )

    assert "ResultsPageViewModel" in app
    assert "ResultsPage" in app
    assert "NavigationRoute.Results" in shell
    assert "new ResultsPageViewModel" in shell
    assert "ItemsSource=\"{Binding VisibleResults, Mode=OneWay}\"" in page
    assert "SelectedItem=\"{Binding SelectedResult, Mode=TwoWay}\"" in page
    assert "加载安全预览" in page
    for disallowed in ("WebView", "http://localhost", "Electron", "SliceDHelper"):
        assert disallowed not in page


def test_results_center_is_retained_in_2381() -> None:
    assert read("src/picotoopet_core/product-version.txt").strip() == "2.3.8.1"
