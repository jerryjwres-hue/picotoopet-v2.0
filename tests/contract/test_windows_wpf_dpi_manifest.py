from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"


def test_wpf_manifest_declares_per_monitor_v2_dpi_awareness() -> None:
    """WPF must render at each monitor's DPI instead of relying on OS bitmap scaling."""
    manifest = (DESKTOP / "app.manifest").read_text(encoding="utf-8-sig")
    project = (DESKTOP / "PicotooPet.Desktop.csproj").read_text(encoding="utf-8-sig")

    assert "<ApplicationManifest>app.manifest</ApplicationManifest>" in project
    assert "<ApplicationHighDpiMode>PerMonitorV2</ApplicationHighDpiMode>" in project
    assert "http://schemas.microsoft.com/SMI/2005/WindowsSettings" in manifest
    assert "http://schemas.microsoft.com/SMI/2016/WindowsSettings" in manifest
    assert ">true/pm</dpiAware>" in manifest
    assert ">PerMonitorV2</dpiAwareness>" in manifest
