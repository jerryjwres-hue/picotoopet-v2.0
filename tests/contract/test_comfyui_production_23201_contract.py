"""冻结 2.3.20.1 ComfyUI 本地生产边界，并证明它保留在当前累计版本。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

EXPECTED_PRODUCT_VERSION = "2.3.27.1"
EXPECTED_DATABASE_SCHEMA = 18
EXPECTED_PROFILE = "production.comfyui.v1"
EXPECTED_COMFY_ENDPOINT = "http://127.0.0.1:8188"
EXPECTED_WORKFLOW_IDS = {
    "comfy.wan22.ti2v5b.t2v.v1",
    "comfy.wan22.ti2v5b.i2v.v1",
}

PRODUCTION_FILES = (
    ROOT / "src/picotoopet_core/db/migration_013.py",
    ROOT / "src/picotoopet_core/production/__init__.py",
    ROOT / "src/picotoopet_core/production/models.py",
    ROOT / "src/picotoopet_core/production/repository.py",
    ROOT / "src/picotoopet_core/production/compiler.py",
    ROOT / "src/picotoopet_core/production/profile.py",
    ROOT / "src/picotoopet_core/production/quality.py",
    ROOT / "src/picotoopet_core/production/service.py",
    ROOT / "src/picotoopet_core/api/routes/production.py",
)

WINDOWS_PRODUCTION_FILES = (
    ROOT / "windows/production/workflows/wan22-ti2v5b-t2v-api-v1.json",
    ROOT / "windows/production/workflows/wan22-ti2v5b-i2v-api-v1.json",
    ROOT / "windows/desktop/src/PicotooPet.Desktop.Core/Contracts/ProductionContracts.cs",
    ROOT / "windows/desktop/src/PicotooPet.Desktop.Core/Production/ComfyProductionClient.cs",
    ROOT / "windows/desktop/src/PicotooPet.Desktop.Core/Production/ComfyWorkflowTemplateValidator.cs",
    ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/ProductionExecutionService.cs",
    ROOT / "windows/desktop/src/PicotooPet.Desktop/ViewModels/ProductionPanelViewModel.cs",
    ROOT / "windows/desktop/src/PicotooPet.Desktop/Views/ProductionPanel.xaml",
)

FORBIDDEN_PRODUCER_FIELDS = {
    "endpoint",
    "base_url",
    "workflow",
    "workflow_json",
    "node_class",
    "model_filename",
    "model_path",
    "command",
    "shell",
    "url",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_production_is_retained_while_current_product_and_schema_advance() -> None:
    version = read(ROOT / "src/picotoopet_core/product-version.txt").strip()
    database = read(ROOT / "src/picotoopet_core/db/database.py")

    assert version == EXPECTED_PRODUCT_VERSION
    assert "MIGRATION_013" in database
    assert "MIGRATION_014" in database
    assert "MIGRATION_015" in database
    assert "MIGRATION_016" in database
    assert "MIGRATION_017" in database
    assert "MIGRATION_018" in database
    # Rollup gate: Production v1 remains in the current schema-18 cumulative 27.1 product.
    assert f"version = {EXPECTED_DATABASE_SCHEMA}" in database


def test_closed_production_runtime_is_present() -> None:
    missing = [str(path.relative_to(ROOT)) for path in PRODUCTION_FILES if not path.is_file()]
    assert missing == []


def test_windows_closed_comfy_executor_surface_is_present() -> None:
    missing = [str(path.relative_to(ROOT)) for path in WINDOWS_PRODUCTION_FILES if not path.is_file()]
    assert missing == []


def test_production_profile_and_workflows_are_fixed_in_source() -> None:
    profile_source = read(ROOT / "src/picotoopet_core/production/profile.py")
    assert EXPECTED_PROFILE in profile_source
    assert EXPECTED_COMFY_ENDPOINT in profile_source
    for workflow_id in EXPECTED_WORKFLOW_IDS:
        assert workflow_id in profile_source


def test_create_contract_does_not_accept_renderer_authority() -> None:
    models_source = read(ROOT / "src/picotoopet_core/production/models.py")
    assert "class ProductionJobCreateRequest" in models_source
    for field_name in FORBIDDEN_PRODUCER_FIELDS:
        assert f"{field_name}:" not in models_source


def test_windows_business_page_hosts_production_without_new_shell_route() -> None:
    page = read(ROOT / "windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml")
    self_test = read(ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/AppSelfTest.cs")

    assert "ProductionPanel" in page
    assert "shell.NavigationItems.Count != 6" in self_test
    assert "PHASE26_OPERATOR_SIMPLE_MODE_SELF_TEST=PASS" in self_test
    assert "NavigationRoute.Production" not in self_test
