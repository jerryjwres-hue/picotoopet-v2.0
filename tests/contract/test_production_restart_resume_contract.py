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


def test_hidden_autonomous_goal_ready_package_uses_only_existing_cpu_delivery() -> None:
    # ── Real-world old Goal can have an exact trusted continuation while hidden
    # ── from the GUI-visible Goal list; this must not authorize GPU execution.
    source = (ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/P0MediaWorkerHost.cs").read_text(encoding="utf-8")
    journal = source.index("var pending = await pendingRecovery.ReconcileAsync")
    visible = source.index("var goals = await session.GetGoalsAsync", journal)
    ready_jobs = source.index("var readyJobs = await session.GetProductionJobsAsync", visible)
    recovery = source.index("session.FinalVideoDelivery.Observe(hiddenGoalId, hiddenContinuation)", ready_jobs)
    end = source.index("} // ── End fresh Goal dispatch", recovery)
    assert journal < visible < ready_jobs < recovery < end
    guarded = source[ready_jobs:recovery]
    for requirement in (
        'completedJob.Status != "production_ready"',
        '"autonomous-goal:"',
        'Guid.TryParseExact(hiddenGoalId, "D"',
        "GetGoalVideoContinuationAsync(",
        "hiddenContinuation.ProductionJobId != completedJob.ProductionJobId",
        'hiddenContinuation.ProductionStatus != "production_ready"',
        "GetProductionPackageAsync(",
        'completedPackage.QualityOutcome != "PASS"',
        "completedPackage.PlanDigest != completedJob.PlanDigest",
    ):
        assert requirement in guarded
    assert "executor.RunAsync" not in source[ready_jobs:end]
    assert "ClaimProductionJobAsync" not in source[ready_jobs:end]
    assert "ComfyProductionClient" not in source[ready_jobs:end]


def test_headless_postproduction_failure_has_redacted_diagnostic() -> None:
    # ── No new log of user-authored text or authentication secrets.
    coordinator = (ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/PostProductionDeliveryCoordinator.cs").read_text(encoding="utf-8")
    session = (ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.cs").read_text(encoding="utf-8")
    assert "failureReporter: session.LogPostProductionFailure" in coordinator
    assert coordinator.count("_failureReporter?.Invoke(goalId, jobId, stage, error)") == 2
    assert "P0_POSTPRODUCTION_FAILED" in session
    assert '"UNCLASSIFIED"' in session


def test_headless_postproduction_reports_typed_api_status_by_stage_and_retries_5xx_only() -> None:
    # ── 500 retry is CPU-only and cannot loosen the upstream exact GPU HOLD gate.
    # ── The authenticated HTTP response body and user-authored text never enter logs.
    coordinator = (ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/PostProductionDeliveryCoordinator.cs").read_text(encoding="utf-8")
    session = (ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.cs").read_text(encoding="utf-8")
    for stage in ("PLAN_FETCH", "PLAN_VALIDATE", "C004_ASSEMBLE",
                  "NARRATION_SYNTHESIZE", "OVERLAY_RENDER", "C009_MASTER",
                  "C011_AUTHORITY", "C011_VERIFY", "C011_PERSIST"):
        assert f'stage = "{stage}"' in coordinator
    assert coordinator.count("_failureReporter?.Invoke(goalId, jobId, stage, error)") == 2
    assert "api.StatusCode is 408 or 429 or >= 500 and <= 599" in coordinator
    assert "api?.Code ?? error.Message" in session
    assert "api?.StatusCode ?? 0" in session
    assert "http_status={status} code={code}" in session
    assert "stage={stage} exception_type=" in session
