"""Source-surface contract retained from the 2.3.16.x platform foundation."""

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
    assert not missing, f"2.3.16.x foundation surfaces are missing: {missing}"


def test_product_version_retains_platform_foundation_in_current_rollup() -> None:
    version = (ROOT / "src/picotoopet_core/product-version.txt").read_text(encoding="utf-8").strip()
    # Version retention gate     Platform foundation remains present in cumulative 23.1.
    assert version == "2.3.23.1"
