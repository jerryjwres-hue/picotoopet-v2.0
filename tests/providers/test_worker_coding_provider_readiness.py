from __future__ import annotations

from pathlib import Path

from picotoopet_core.providers.models import ProviderReadinessStatus


class FakeProjection:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def publish(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return kwargs


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeCodexProbe:
    def __init__(self) -> None:
        self.calls = 0
        self.result = ProviderReadinessStatus.READY

    def status(self) -> ProviderReadinessStatus:
        self.calls += 1
        return self.result


class FakeClaudeProbe:
    def __init__(self) -> None:
        self.calls = 0
        self.result = "not_authenticated"

    def probe_readiness(self, *, cwd: Path) -> str:
        assert cwd.name == "repo"
        self.calls += 1
        return self.result


def test_worker_readiness_refresh_is_cached_for_thirty_seconds(tmp_path: Path) -> None:
    from picotoopet_core.providers.readiness_worker import ProviderReadinessPublisher

    projection = FakeProjection()
    clock = FakeClock()
    codex = FakeCodexProbe()
    claude = FakeClaudeProbe()
    repo = tmp_path / "repo"
    repo.mkdir()
    publisher = ProviderReadinessPublisher(
        projection=projection,
        worker_id="mac-worker-readiness",
        repository=repo,
        codex_executable=tmp_path / "codex",
        claude_code_executable=tmp_path / "claude",
        clock=clock,
        codex_probe=codex,
        claude_probe=claude,
    )

    first = publisher.refresh(force=True)
    publisher.refresh()
    clock.advance(29.9)
    publisher.refresh()

    assert first == {
        "codex": ProviderReadinessStatus.READY,
        "claude_code": ProviderReadinessStatus.NOT_AUTHENTICATED,
    }
    assert codex.calls == 1
    assert claude.calls == 1
    assert len(projection.calls) == 2

    clock.advance(0.2)
    publisher.refresh()
    assert codex.calls == 2
    assert claude.calls == 2
    assert len(projection.calls) == 4


def test_unconfigured_provider_is_never_probed_or_published(tmp_path: Path) -> None:
    from picotoopet_core.providers.readiness_worker import ProviderReadinessPublisher

    projection = FakeProjection()
    codex = FakeCodexProbe()
    claude = FakeClaudeProbe()
    repo = tmp_path / "repo"
    repo.mkdir()
    publisher = ProviderReadinessPublisher(
        projection=projection,
        worker_id="claude-only",
        repository=repo,
        codex_executable=None,
        claude_code_executable=tmp_path / "claude",
        codex_probe=codex,
        claude_probe=claude,
    )

    publisher.refresh(force=True)

    assert codex.calls == 0
    assert claude.calls == 1
    assert publisher.status("codex") is ProviderReadinessStatus.UNAVAILABLE
    assert publisher.status("claude_code") is ProviderReadinessStatus.NOT_AUTHENTICATED
    assert [call["provider"] for call in projection.calls] == ["claude_code"]


def test_shutdown_publishes_unavailable_only_for_configured_providers(tmp_path: Path) -> None:
    from picotoopet_core.providers.readiness_worker import ProviderReadinessPublisher

    projection = FakeProjection()
    repo = tmp_path / "repo"
    repo.mkdir()
    publisher = ProviderReadinessPublisher(
        projection=projection,
        worker_id="codex-only",
        repository=repo,
        codex_executable=tmp_path / "codex",
        claude_code_executable=None,
        codex_probe=FakeCodexProbe(),
        claude_probe=FakeClaudeProbe(),
    )

    publisher.publish_unavailable()

    assert len(projection.calls) == 1
    assert projection.calls[0]["provider"] == "codex"
    assert projection.calls[0]["status"] is ProviderReadinessStatus.UNAVAILABLE


def test_worker_source_wires_cached_readiness_and_queue_gate() -> None:
    root = Path(__file__).resolve().parents[2]
    cli = (root / "src/picotoopet_core/cli.py").read_text(encoding="utf-8")
    execution = (root / "src/picotoopet_core/providers/execution.py").read_text(encoding="utf-8")

    assert "ProviderReadinessPublisher" in cli
    assert "provider_readiness.refresh(force=True)" in cli
    assert "provider_readiness.refresh()" in cli
    assert "provider_readiness.publish_unavailable()" in cli
    assert "readiness_by_provider=provider_readiness.status" in cli
    assert "readiness_by_provider" in execution
    assert "ProviderReadinessStatus.READY" in execution
