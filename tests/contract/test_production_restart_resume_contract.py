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


def test_finished_package_finalization_is_not_blocked_by_gpu_hold() -> None:
    # ── Journal uncertainty still blocks ALL fresh dispatch before CPU QA.
    # ── A ready existing package needs no new GPU claim, even when HOLD.
    host = ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/P0MediaWorkerHost.cs"
    source = host.read_text(encoding="utf-8")
    start = source.index("var pending = await pendingRecovery.ReconcileAsync")
    ready = source.index('if (continuation.ProductionStatus is "production_ready")', start)
    observe = source.index("session.FinalVideoDelivery.Observe", ready)
    allow = source.index("P0ThreeShotAcceptanceGate.AllowsJobAsync(", observe)
    execute = source.index("await executor.RunAsync(jobId", allow)
    assert start < ready < observe < allow < execute
    # ── No new executor/Claim/Comfy path can enter the ready branch.
    # ── Ignore comment text when checking for executable renderer calls.
    ready_branch = "\n".join(
        line.split("//", 1)[0] for line in source[ready:allow].splitlines()
    )
    assert "executor.RunAsync" not in ready_branch
    assert "ClaimProductionJobAsync" not in ready_branch
    assert "ComfyProductionClient" not in ready_branch
    # ── The old journal-recovery branch remains the outer dispatch barrier.
    assert "if (pending.HasPending)" in source[start:ready]
