"""Freeze the cumulative 2.3.22.1 Paid-AI Escalation + Quality Learning delivery boundary."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CURRENT_PRODUCT_VERSION = "2.3.26.1"
CURRENT_DATABASE_SCHEMA = 18
PAID_AI_DATABASE_SCHEMA = 15


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_current_product_and_schema_advance_while_23221_is_retained() -> None:
    # Rollup gate: 22.1 remains frozen at schema 15 inside current 26.1/schema 18.
    assert read("src/picotoopet_core/product-version.txt").strip() == CURRENT_PRODUCT_VERSION
    database = read("src/picotoopet_core/db/database.py")
    assert "MIGRATION_015" in database
    assert "MIGRATION_016" in database
    assert "MIGRATION_017" in database
    assert "MIGRATION_018" in database
    assert f"version = {CURRENT_DATABASE_SCHEMA}" in database


def test_paid_ai_policy_is_source_controlled_bounded_and_disabled_by_default() -> None:
    policy = read("src/picotoopet_core/deep_ai/policy.py")
    for required in (
        'provider_profile_id="paid.reasoning.v1"',
        'provider_adapter_id="openai.responses.v1"',
        'model_id="gpt-5.6-terra"',
        "max_calls=2",
        'max_cost_usd=Decimal("0.50")',
        "execution_enabled=False",
    ):
        assert required in policy


def test_paid_execution_reserves_before_provider_submit_and_fails_closed_on_ambiguity() -> None:
    execution = read("src/picotoopet_core/deep_ai/execution.py")
    assert execution.index("self.repository.reserve_attempt(") < execution.index(
        "self.provider.execute("
    )
    assert "ProviderTransportAmbiguous" in execution
    assert "DEEP_AI_PROVIDER_AMBIGUOUS" in execution
    assert "DEEP_AI_BUDGET_PREFLIGHT_FAILED" in execution
    assert "DEEP_AI_ACTUAL_USAGE_EXCEEDED" in execution


def test_result_processing_has_no_paid_provider_execution_authority() -> None:
    processing = read("src/picotoopet_core/deep_ai/result_processing.py")
    assert "DeepAiResultValidator" in processing
    assert "DeepAiContinuation" in processing
    assert "DeepAiLearningLedger" in processing
    assert "self.provider.execute(" not in processing
    assert "OpenAI" not in processing


def test_api_and_windows_surface_are_bounded_without_provider_configuration_authority() -> None:
    api = read("src/picotoopet_core/api/routes/deep_ai.py")
    page = read("windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml")
    panel = read("windows/desktop/src/PicotooPet.Desktop/Views/DeepAiEscalationPanel.xaml")
    view_model = read(
        "windows/desktop/src/PicotooPet.Desktop/ViewModels/DeepAiEscalationPanelViewModel.cs"
    )
    shell_self_test = read("windows/desktop/src/PicotooPet.Desktop/Services/AppSelfTest.cs")

    assert 'model_config = ConfigDict(extra="forbid")' in api
    assert "DeepAiEscalationPanel" in page
    assert "批准不等于自动花钱" in panel
    assert "不会自动提高预算" in panel
    assert "TextBox" not in panel
    assert "ComboBox" not in panel
    for forbidden in ("Endpoint", "ApiKey", "ProviderKey", "Prompt", "Temperature"):
        assert forbidden not in view_model
    assert "shell.NavigationItems.Count != 11" in shell_self_test


def test_release_goal_contract_records_paid_ai_quality_learning_without_rewriting_history() -> None:
    contract = json.loads(read("contracts/release/project-goal-invariants.json"))
    architecture = contract["architecture"]
    assert architecture["business_automation_v1"]["database_schema"] == 11
    assert architecture["creative_intelligence_v1"]["database_schema"] == 12
    assert architecture["comfyui_production_v1"]["database_schema"] == 13
    assert architecture["end_to_end_business_automation_v1"]["database_schema"] == 14

    paid = architecture["paid_ai_quality_learning_v1"]
    assert paid["database_schema"] == PAID_AI_DATABASE_SCHEMA
    assert paid["source_state"] == "NEEDS_DEEP_AI"
    assert paid["provider_profile"] == "paid.reasoning.v1"
    assert paid["provider_adapter"] == "openai.responses.v1"
    assert paid["model_id"] == "gpt-5.6-terra"
    assert paid["default_execution_enabled"] is False
    assert paid["max_calls"] == 2
    assert paid["max_cost_usd"] == "0.50"
    assert paid["reserve_before_submit"] is True
    assert paid["ambiguous_transport_state"] == "NeedsHuman"
    assert paid["deterministic_validation"] is True
    assert paid["pass_continues_source"] is True
    assert paid["quality_learning"] == "append-only-facts"
    assert paid["feedback_actions"] == ["Accepted", "Rejected", "Modified"]
    assert paid["automatic_policy_mutation"] is False
    assert paid["automatic_prompt_mutation"] is False
    assert paid["automatic_provider_switch"] is False
    assert paid["automatic_model_switch"] is False
    assert paid["automatic_budget_raise"] is False
    assert paid["provider_tools"] is False
    assert paid["automatic_publish"] is False
    assert paid["windows_provider_configuration_authority"] is False
