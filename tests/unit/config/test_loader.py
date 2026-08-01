from pathlib import Path

from picotoopet_core.config.loader import load_settings


def test_load_settings_uses_environment_and_redacts_secrets(
    monkeypatch, tmp_path: Path
) -> None:
    """环境变量应覆盖默认值，输出配置时不得泄露令牌。"""

    monkeypatch.setenv("PICOTOO_RUNTIME_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("PICOTOO_API_TOKEN", "super-secret-token")
    monkeypatch.setenv("PICOTOO_OLLAMA_MODEL", "gpt-oss:20b")

    settings = load_settings()
    redacted = settings.redacted_dict()

    assert settings.paths.root == (tmp_path / "state").resolve()
    assert settings.ollama_model == "gpt-oss:20b"
    assert redacted["api_token"] == "***REDACTED***"
    assert "super-secret-token" not in str(redacted)
