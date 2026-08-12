from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "src" / "picotoopet_core" / "cli.py"
SETTINGS = ROOT / "src" / "picotoopet_core" / "config" / "models.py"
PROVIDER = ROOT / "src" / "picotoopet_core" / "deep_ai" / "provider.py"


def test_paid_ai_is_worker_only_and_disabled_by_default() -> None:
    cli = CLI.read_text(encoding="utf-8")
    settings = SETTINGS.read_text(encoding="utf-8")
    provider = PROVIDER.read_text(encoding="utf-8")

    assert "DeepAiWorkerProviderConfig.from_environment(os.environ)" in cli
    assert "OpenAiResponsesPaidAiAdapter" in cli
    assert "DeepAiWorkerExecutionLoop" in cli
    assert 'capability=DeepAiWorkerExecutionLoop.CAPABILITY' in cli
    assert "deep_ai_execution_loop.run_once()" in cli
    assert "deep_ai_provider_config.redacted_dict()" in cli

    # Secrets are Worker-process-only. AppSettings/Core SQLite must not gain a paid API key field.
    assert "OPENAI_API_KEY" not in settings
    assert "paid_ai_api_key" not in settings
    assert "api_key: SecretStr | None" in provider
    assert 'PICOTOOPET_PAID_AI_EXECUTION_ENABLED' in provider
    assert 'OPENAI_API_KEY' in provider


def test_worker_does_not_expose_paid_endpoint_or_model_override_environment_variables() -> None:
    provider = PROVIDER.read_text(encoding="utf-8")
    assert 'environment.get("PICOTOOPET_PAID_AI_ENDPOINT"' not in provider
    assert 'environment.get("PICOTOOPET_PAID_AI_MODEL"' not in provider
    assert 'endpoint: str = "https://api.openai.com/v1/responses"' in provider
    assert 'model_id: str = "gpt-5.6-terra"' in provider
