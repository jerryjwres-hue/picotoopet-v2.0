from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/ProductionExecutionService.cs"


def test_executor_reserves_attempt_before_submitting_comfy_prompt() -> None:
    # ── Core must accept the attempt before any GPU work can become orphaned ─
    source = EXECUTOR.read_text(encoding="utf-8")
    submit = source.index("_comfy.SubmitPromptAsync")
    marker = "await _session.MarkProductionAttemptAsync("
    first_mark = source.index(marker)
    second_mark = source.index(marker, first_mark + len(marker))

    # ── The first Core write is the null prompt reservation; bind follows submit ─
    first_segment = source[first_mark:submit]
    second_segment = source[submit:second_mark + 500]
    assert "new ProductionTaskAttemptRequest(_executorId, claim.LeaseToken, null)" in first_segment
    assert "new ProductionTaskAttemptRequest(_executorId, claim.LeaseToken," in second_segment
    assert first_mark < submit < second_mark
