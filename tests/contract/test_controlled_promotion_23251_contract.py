"""Freeze the cumulative 2.3.25.1 Controlled Promotion / Rollback governance boundary."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CURRENT_PRODUCT_VERSION = "2.3.25.1"
CURRENT_DATABASE_SCHEMA = 18


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_current_product_schema_and_promotion_surfaces_are_frozen() -> None:
    assert read("src/picotoopet_core/product-version.txt").strip() == CURRENT_PRODUCT_VERSION
    database = read("src/picotoopet_core/db/database.py")
    assert "MIGRATION_017" in database
    assert "MIGRATION_018" in database
    assert "version = 18" in database
    for path in (
        "src/picotoopet_core/db/migration_018.py",
        "src/picotoopet_core/deep_ai/promotion.py",
        "src/picotoopet_core/api/routes/quality_promotion.py",
        "windows/desktop/src/PicotooPet.Desktop.Core/Contracts/QualityPromotionContracts.cs",
        "windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreQualityPromotionClient.cs",
        "windows/desktop/src/PicotooPet.Desktop/ViewModels/QualityPromotionPanelViewModel.cs",
        "windows/desktop/src/PicotooPet.Desktop/Views/QualityPromotionPanel.xaml",
        "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/QualityPromotionPanelWpfSmokeTests.cs",
    ):
        assert (ROOT / path).is_file(), path


def test_promotion_api_and_windows_have_no_executable_policy_authority() -> None:
    api = read("src/picotoopet_core/api/routes/quality_promotion.py")
    promotion = read("src/picotoopet_core/deep_ai/promotion.py")
    contracts = read(
        "windows/desktop/src/PicotooPet.Desktop.Core/Contracts/QualityPromotionContracts.cs"
    )
    panel = read("windows/desktop/src/PicotooPet.Desktop/Views/QualityPromotionPanel.xaml")
    business_page = read(
        "windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml"
    )

    assert 'promotion_profile_id: Literal["quality.promotion.v1"]' in promotion
    assert 'model_config = ConfigDict(extra="forbid")' in api
    assert "shadow_run_id: str" in api
    assert "QualityPromotionPanel" in business_page
    assert "TextBox" not in panel
    assert 'Mode=OneWay' in panel
    assert "RegressionObserved" in panel or "RollbackReasons" in read(
        "windows/desktop/src/PicotooPet.Desktop/ViewModels/QualityPromotionPanelViewModel.cs"
    )
    for forbidden in (
        "PromptInput",
        "ModelInput",
        "ProviderInput",
        "EndpointInput",
        "ApiKeyInput",
        "BudgetInput",
        "WorkflowInput",
        "CommandInput",
        "PatchInput",
    ):
        assert forbidden not in contracts
        assert forbidden not in panel


def test_release_goal_preserves_history_and_adds_governance_only_promotion() -> None:
    goal = json.loads(read("contracts/release/project-goal-invariants.json"))
    assert goal["windows"]["product_version"]["value"] == CURRENT_PRODUCT_VERSION
    architecture = goal["architecture"]
    assert architecture["business_automation_v1"]["database_schema"] == 11
    assert architecture["creative_intelligence_v1"]["database_schema"] == 12
    assert architecture["comfyui_production_v1"]["database_schema"] == 13
    assert architecture["end_to_end_business_automation_v1"]["database_schema"] == 14
    assert architecture["paid_ai_quality_learning_v1"]["database_schema"] == 15
    assert architecture["offline_quality_evaluation_v1"]["database_schema"] == 16
    assert architecture["controlled_shadow_validation_v1"]["database_schema"] == 17

    promotion = architecture["controlled_promotion_rollback_v1"]
    assert promotion["database_schema"] == 18
    assert promotion["promotion_profile"] == "quality.promotion.v1"
    assert promotion["activation_exact_request_digest"] is True
    assert promotion["rollback_exact_request_digest"] is True
    assert promotion["one_active_per_slot"] is True
    assert promotion["active_record_consumed_by_runtime"] is False
    assert promotion["runtime_policy_mutation"] is False
    assert promotion["automatic_prompt_mutation"] is False
    assert promotion["automatic_model_switch"] is False
    assert promotion["automatic_provider_switch"] is False
    assert promotion["automatic_endpoint_change"] is False
    assert promotion["automatic_budget_change"] is False
    assert promotion["local_ai_execution"] is False
    assert promotion["paid_ai_execution"] is False
    assert promotion["comfyui_execution"] is False
    assert promotion["publication_execution"] is False
    assert promotion["git_execution"] is False
    assert promotion["github_execution"] is False
    assert promotion["automatic_merge"] is False
    assert promotion["automatic_tag"] is False
    assert promotion["automatic_release"] is False


def test_real_wpf_smoke_is_registered_and_no_top_level_route_is_added() -> None:
    program = read(
        "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs"
    )
    smoke = read(
        "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/QualityPromotionPanelWpfSmokeTests.cs"
    )
    self_test = read("windows/desktop/src/PicotooPet.Desktop/Services/AppSelfTest.cs")

    assert "QualityPromotionPanelWpfSmokeTests.Run();" in program
    for required in (
        "new QualityPromotionPanel",
        "Measure(new Size(1100, 780))",
        "Arrange(new Rect(0, 0, 1100, 780))",
        "UpdateLayout()",
        "BindingMode.OneWay",
    ):
        assert required in smoke
    assert "shell.NavigationItems.Count != 11" in self_test
    assert "NavigationRoute.Promotion" not in self_test
