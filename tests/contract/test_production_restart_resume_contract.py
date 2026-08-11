from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/ProductionExecutionService.cs"
POLICY = ROOT / "windows/desktop/src/PicotooPet.Desktop.Core/Production/ProductionResumePolicy.cs"


def test_executor_filters_claim_tasks_before_any_render_submission() -> None:
    # ── Restart-safe resume must be explicit in the executor source ─────────
    source = EXECUTOR.read_text(encoding="utf-8")
    assert "ProductionResumePolicy.TasksToRender(claim)" in source
    assert "foreach (var task in ProductionResumePolicy.TasksToRender(claim))" in source


def test_resume_policy_is_a_core_level_deterministic_contract() -> None:
    # ── Policy belongs in Desktop.Core so CI can test it without GPU/WPF ────
    source = POLICY.read_text(encoding="utf-8")
    assert "status is Succeeded" in source or '"Succeeded"' in source
    assert "attempt" in source.lower()
