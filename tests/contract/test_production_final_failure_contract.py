from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/ProductionExecutionService.cs"
SESSION_FAILURE = ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.ProductionFailure.cs"
CLIENT_FAILURE = ROOT / "windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.ProductionFailure.cs"


def test_executor_durably_reports_final_render_failure_to_core() -> None:
    # ── System failure and user cancellation must remain distinct states ─────
    source = EXECUTOR.read_text(encoding="utf-8")
    assert "FailProductionTaskAsync" in source
    assert "COMFY_RETRY_BUDGET_EXHAUSTED" in source


def test_failure_transport_is_a_bounded_production_endpoint() -> None:
    # ── Dedicated partial files keep the failure write surface auditable ─────
    session = SESSION_FAILURE.read_text(encoding="utf-8")
    client = CLIENT_FAILURE.read_text(encoding="utf-8")
    assert "FailProductionTaskAsync" in session
    assert "FailProductionTaskAsync" in client
    assert "/failure" in client
