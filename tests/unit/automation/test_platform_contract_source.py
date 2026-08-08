"""Source-surface RED contract for 2.3.16.1 Windows/platform completion."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_platform_foundation_source_surfaces_exist() -> None:
    required = [
        ROOT / "src/picotoopet_core/automation/models.py",
        ROOT / "src/picotoopet_core/automation/service.py",
        ROOT / "src/picotoopet_core/automation/capabilities.py",
        ROOT / "src/picotoopet_core/automation/quality.py",
        ROOT / "src/picotoopet_core/automation/continuation.py",
        ROOT / "windows/desktop/src/PicotooPet.Desktop/Views/Pages/ProjectsPage.xaml",
        ROOT / "windows/desktop/src/PicotooPet.Desktop/Views/Pages/AutomationPage.xaml",
        ROOT / "windows/desktop/src/PicotooPet.Desktop/Views/Pages/HealthPage.xaml",
        ROOT / "windows/desktop/src/PicotooPet.Desktop/Views/Pages/DiagnosticsPage.xaml",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    assert not missing, f"2.3.16.1 foundation surfaces are missing: {missing}"


def test_product_version_advances_for_new_capability() -> None:
    version = (ROOT / "src/picotoopet_core/product-version.txt").read_text(encoding="utf-8").strip()
    assert version == "2.3.16.1"
