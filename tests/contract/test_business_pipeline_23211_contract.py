"""Release-freeze contract for PicotooPet 2.3.21.1 End-to-End Business Automation V1."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "picotoopet_core"
WINDOWS = ROOT / "windows" / "desktop"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_product_version_and_schema_are_current_while_23211_is_retained() -> None:
    # Rollup gate              21.1 remains present while current product advances to 24.1/schema 17.
    assert read(CORE / "product-version.txt").strip() == "2.3.24.1"

    database = read(CORE / "db" / "database.py")
    migration = read(CORE / "db" / "migration_014.py")
    assert "from .migration_014 import MIGRATION_014" in database
    assert "MIGRATION_015" in database
    assert "MIGRATION_016" in database
    assert "MIGRATION_017" in database
    assert "version = 17" in database
    assert "executescript(MIGRATION_014)" in database
    assert "business_pipeline_runs" in migration
    assert "business_return_packages" in migration


def test_business_pipeline_api_is_closed_and_complete() -> None:
    models = read(CORE / "business_pipeline" / "models.py")
    routes = read(CORE / "api" / "routes" / "business_pipeline.py")
    app = read(CORE / "api" / "app.py")

    request_block = models.split("class BusinessPipelineRunCreateRequest", 1)[1]
    request_block = request_block.split("class ", 1)[0]
    assert 'extra="forbid"' in request_block
    for required in ("work_package_id:", "adapter_profile:", "idempotency_key:"):
        assert required in request_block
    for forbidden in ("model_id", "endpoint", "workflow_json", "command", "provider"):
        assert f"{forbidden}:" not in request_block

    for route in (
        '@router.post("/business-pipeline/runs"',
        '@router.get("/business-pipeline/runs"',
        '@router.get("/business-pipeline/runs/{pipeline_run_id}"',
        '@router.post("/business-pipeline/runs/{pipeline_run_id}/reconcile"',
        '@router.post("/business-pipeline/runs/{pipeline_run_id}/cancel"',
        '"/business-pipeline/runs/{pipeline_run_id}/return-package"',
        '@router.get("/business-pipeline/runs/{pipeline_run_id}/return-package/archive")',
    ):
        assert route in routes
    assert "app.include_router(business_pipeline.router" in app


def test_windows_release_contains_only_first_party_adapters_and_real_wpf_gate() -> None:
    adapter_base = read(
        WINDOWS
        / "src"
        / "PicotooPet.Desktop.Core"
        / "BusinessPipeline"
        / "BusinessWorkPackageAdapter.cs"
    )
    amazon = read(
        WINDOWS
        / "src"
        / "PicotooPet.Desktop.Core"
        / "BusinessPipeline"
        / "AmazonReviewsAdapter.cs"
    )
    inspiration = read(
        WINDOWS
        / "src"
        / "PicotooPet.Desktop.Core"
        / "BusinessPipeline"
        / "InspirationIdeasAdapter.cs"
    )
    panel = read(
        WINDOWS / "src" / "PicotooPet.Desktop" / "Views" / "BusinessPipelinePanel.xaml"
    )
    wpf_smoke = read(
        WINDOWS
        / "tests"
        / "PicotooPet.Desktop.Core.SmokeTests"
        / "BusinessPipelinePanelWpfSmokeTests.cs"
    )
    program = read(
        WINDOWS / "tests" / "PicotooPet.Desktop.Core.SmokeTests" / "Program.cs"
    )

    assert '"amazon.reviews_export.v1"' in amazon
    assert '"reviews.voice_of_customer.v1"' in amazon
    assert '"inspiration.ideas_export.v1"' in inspiration
    assert '"ideas.pattern_analysis.v1"' in inspiration
    for forbidden in ("ModelId", "Endpoint", "Workflow", "Command", "Provider"):
        assert forbidden not in adapter_base
    assert 'Text="{Binding SourcePath, Mode=OneWay}"' in panel
    assert 'IsReadOnly="True"' in panel
    assert "BusinessPipelinePanelWpfSmokeTests.Run();" in program
    for required in (
        "new BusinessPipelinePanel",
        "Measure(new Size(1100, 560))",
        "Arrange(new Rect(0, 0, 1100, 560))",
        "UpdateLayout()",
        "BindingMode.OneWay",
    ):
        assert required in wpf_smoke


def test_20_1_production_boundary_remains_frozen() -> None:
    production = read(
        WINDOWS
        / "src"
        / "PicotooPet.Desktop"
        / "ViewModels"
        / "ProductionPanelViewModel.cs"
    )
    comfy = read(
        WINDOWS
        / "src"
        / "PicotooPet.Desktop.Core"
        / "Production"
        / "ComfyProductionClient.cs"
    )
    assert 'FixedProductionProfile = "production.comfyui.v1"' in production
    assert 'ProductionBoundaryText = "production_ready != publish-ready"' in production
    assert "http://127.0.0.1:8188" in comfy
