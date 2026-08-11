from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_creative_intelligence_required_surfaces_exist() -> None:
    required = (
        "src/picotoopet_core/db/migration_012.py",
        "src/picotoopet_core/creative/models.py",
        "src/picotoopet_core/creative/repository.py",
        "src/picotoopet_core/creative/source.py",
        "src/picotoopet_core/creative/profiles.py",
        "src/picotoopet_core/creative/quality.py",
        "src/picotoopet_core/creative/store.py",
        "src/picotoopet_core/creative/execution.py",
        "src/picotoopet_core/creative/service.py",
        "src/picotoopet_core/api/routes/creative_intelligence.py",
        "windows/desktop/src/PicotooPet.Desktop.Core/Contracts/CreativeIntelligenceContracts.cs",
        "windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.CreativeIntelligence.cs",
        "windows/desktop/src/PicotooPet.Desktop/ViewModels/CreativeIntelligencePanelViewModel.cs",
        "windows/desktop/src/PicotooPet.Desktop/Views/CreativeIntelligencePanel.xaml",
        "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/CreativeIntelligenceWpfSmokeTests.cs",
    )
    missing = [path for path in required if not (ROOT / path).is_file()]
    assert missing == [], f"2.3.19.1 missing creative intelligence surfaces: {missing}"


def test_creative_design_boundary_is_closed() -> None:
    design = _read(
        "docs/superpowers/specs/2026-08-10-creative-intelligence-2.3.19.1-design.md"
    )
    for required in (
        "creative.content_plan.v1",
        "creative.intelligence.v1",
        "source_finding_ref",
        "creative_ready",
        "Migration 12",
        "maximum 2",
        "does not automatically call paid AI",
        "execute ComfyUI",
    ):
        assert required in design
