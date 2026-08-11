from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "src/picotoopet_core/production/service.py"
EXECUTOR = ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/ProductionExecutionService.cs"


def test_core_claim_derives_unfinished_only_resume_plan() -> None:
    # ── Core owns the durable snapshot and filters Succeeded shots centrally ─
    source = SERVICE.read_text(encoding="utf-8")
    assert "snapshots = {task.production_task_id: task for task in claim.tasks}" in source
    assert "if snapshot.status is ProductionTaskStatus.SUCCEEDED" in source
    assert 'claim.plan.model_copy(update={"tasks": resume_tasks})' in source
    assert 'claim.model_copy(update={"plan": resume_plan})' in source


def test_windows_executes_only_the_claim_resume_plan() -> None:
    # ── Windows must not fall back to full task snapshots for render selection ─
    source = EXECUTOR.read_text(encoding="utf-8")
    assert "foreach (var task in claim.Plan.Tasks.OrderBy(item => item.Order))" in source
    assert "foreach (var task in claim.Tasks" not in source
