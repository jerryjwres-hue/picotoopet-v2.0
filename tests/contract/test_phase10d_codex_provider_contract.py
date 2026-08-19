"""Phase 10D-A bounded coding Provider static safety contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    path = ROOT / relative
    assert path.is_file(), f"Phase 10D-A 缺少正式文件：{relative}"
    return path.read_text(encoding="utf-8")


def test_phase10d_core_has_separate_provider_domain_and_additive_migration() -> None:
    models = _read("src/picotoopet_core/providers/models.py")
    service = _read("src/picotoopet_core/providers/service.py")
    routes = _read("src/picotoopet_core/api/routes/provider_sessions.py")
    schema = _read("src/picotoopet_core/db/schema.py")
    database = _read("src/picotoopet_core/db/database.py")
    services = _read("src/picotoopet_core/services.py")
    app = _read("src/picotoopet_core/api/app.py")

    assert "class ProviderSessionStatus" in models
    assert 'Literal["codex", "claude_code"]' in models
    assert 'extra="forbid"' in models
    assert "class ProviderSessionService" in service
    assert "MIGRATION_006" in schema
    assert "provider_usage_confirmations" in schema
    assert "provider_sessions" in schema
    assert "MIGRATION_006" in database
    assert "provider_sessions: ProviderSessionService" in services
    assert "provider_sessions.router" in app
    assert "/provider-sessions/codex" in routes
    assert "/provider-usage-confirmation" in routes


def test_phase10d_budget_is_fixed_and_cannot_auto_expand() -> None:
    models = _read("src/picotoopet_core/providers/models.py")
    service = _read("src/picotoopet_core/providers/service.py")

    for required in (
        "max_turns: Literal[8]",
        "timeout_seconds: Literal[900]",
        "max_changed_files: Literal[5]",
        "max_file_bytes: Literal[65536]",
        "max_return_bytes: Literal[262144]",
        "automatic_retries: Literal[0]",
        "network_tools_allowed: Literal[False]",
    ):
        assert required in models

    assert "confirmed_available" in models
    assert "confirmed_low" in models
    assert "confirmed_exhausted" in models
    assert "unknown" in models
    assert "timedelta(minutes=15)" in service
    assert "每个 approved Handoff 只能启动一次真实 Codex Session" in service


def test_phase10d_api_rejects_arbitrary_provider_inputs_and_secrets() -> None:
    models = _read("src/picotoopet_core/providers/models.py")
    routes = _read("src/picotoopet_core/api/routes/provider_sessions.py")

    forbidden_fields = (
        "api_key",
        "access_token",
        "refresh_token",
        "cookie",
        "command",
        "working_directory",
        "model_name",
        "environment",
        "arguments",
    )
    for field in forbidden_fields:
        assert f"{field}:" not in models

    assert "require_empty_body" in routes
    assert "Idempotency-Key" in routes
    assert "response_model=ProviderSessionRecord" in routes
