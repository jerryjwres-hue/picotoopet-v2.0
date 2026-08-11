from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/ProductionExecutionService.cs"


def test_executor_reserves_attempt_before_submitting_comfy_prompt() -> None:
    # ── Core must accept the attempt before any GPU work can become orphaned ─
    source = EXECUTOR.read_text(encoding="utf-8")
    reserve = source.index("new ProductionTaskAttemptRequest(_executorId, claim.LeaseToken, null)")
    submit = source.index("_comfy.SubmitPromptAsync")
    bind = source.index("new ProductionTaskAttemptRequest(_executorId, claim.LeaseToken, promptId)")
    assert reserve < submit < bind
