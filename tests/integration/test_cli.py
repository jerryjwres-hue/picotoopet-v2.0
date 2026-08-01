import json
from pathlib import Path

from picotoopet_core.cli import main


def test_cli_health_creates_database_and_prints_report(tmp_path: Path, monkeypatch, capsys) -> None:
    """CLI 健康命令必须可被 launchd 和双击验证脚本调用。"""

    monkeypatch.setenv("PICOTOO_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("PICOTOO_API_TOKEN", "0123456789abcdef0123456789abcdef")

    exit_code = main(["health", "--skip-ollama"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["status"] == "ok"
    assert (tmp_path / "runtime" / "database" / "core.db").is_file()


def test_cli_resident_check_reports_missing_without_downloading(monkeypatch, capsys) -> None:
    """模型缺失结果必须可被安装验证程序识别。"""

    from picotoopet_core.ollama.resident_manager import ResidentResult, ResidentStatus

    class FakeManager:
        def ensure_resident(self):
            return ResidentResult(
                status=ResidentStatus.MODEL_MISSING,
                model_name="gpt-oss:20b",
                detail="missing",
            )

    monkeypatch.setattr("picotoopet_core.cli._build_resident_manager", lambda settings: FakeManager())
    monkeypatch.setenv("PICOTOO_API_TOKEN", "0123456789abcdef0123456789abcdef")

    exit_code = main(["resident-check"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 3
    assert output["status"] == "model_missing"
