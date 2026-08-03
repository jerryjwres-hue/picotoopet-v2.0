import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "contracts/release/install-regression-cases.json"


def test_task_center_crash_is_a_permanent_windows_release_gate() -> None:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in payload["cases"]}

    incident = cases["WIN-2026-08-02-TASK-CENTER-READONLY-BINDING"]
    assert incident["platform"] == "windows"
    assert incident["status"] == "closed"
    assert "explicit OneWay binding for read-only Run.Text sources" in incident["required_controls"]
    assert "native WPF Task Center layout smoke test" in incident["required_controls"]
    assert "global WPF dispatcher exception logging" in incident["required_controls"]
