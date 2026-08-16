from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"


def test_mixed_wpf_winforms_app_sets_per_monitor_v2_before_wpf_startup() -> None:
    """Mixed WPF/WinForms startup must set process DPI before creating the WPF App."""
    manifest = (DESKTOP / "app.manifest").read_text(encoding="utf-8-sig")
    project = (DESKTOP / "PicotooPet.Desktop.csproj").read_text(encoding="utf-8-sig")
    program = (DESKTOP / "Program.cs").read_text(encoding="utf-8-sig")

    assert "<ApplicationManifest>app.manifest</ApplicationManifest>" in project
    assert "<ApplicationHighDpiMode>PerMonitorV2</ApplicationHighDpiMode>" in project
    assert "<dpiAware" not in manifest
    assert "<dpiAwareness" not in manifest

    call = "System.Windows.Forms.Application.SetHighDpiMode(System.Windows.Forms.HighDpiMode.PerMonitorV2);"
    assert call in program
    assert program.index(call) < program.index("var application = new App();")
